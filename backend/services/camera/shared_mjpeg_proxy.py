"""Shared MJPEG proxy — one upstream connection, many downstream subscribers.

The single-client :class:`services.camera_mjpeg_proxy.MjpegProxy` opens one
upstream httpx connection per ``/stream`` request. With N browser tabs
viewing the same camera we get N redundant upstream connections. For
IP cameras that hard-cap concurrent MJPEG clients (most do, at 1–3)
this is exactly the failure mode that turns the operator's dashboard
into "needs a page reload to come back" — every new tab is a fresh
upstream TCP connection, and once the camera's connection table is
full the next retry is refused until the upstream times out the
stale sockets.

This module replaces the per-request proxy with a fan-out proxy:

* one ``httpx.AsyncClient`` per upstream URL;
* one background ``pump_task`` that reads ``response.aiter_bytes(...)``;
* each subscriber gets its own bounded ``asyncio.Queue``; the pump
  pushes each chunk into every queue;
* a slow subscriber's queue overflows → drop the **oldest** queued
  chunk for that subscriber only (others keep streaming). The MJPEG
  browser resyncs on the next JPEG boundary;
* the upstream closes 2 s after the last subscriber leaves (idle
  TTL) so a quick reload reuses the existing socket instead of
  opening a brand-new one;
* on upstream error the pump cancels every subscriber queue with
  ``StopAsyncIteration`` — a coordinated disconnect replaces the
  thundering-herd reconnect that the per-request proxy used to
  produce.

The module-level :class:`MjpegFanout` registry owns the
``Dict[url, SharedMjpegProxy]`` and is the only API the camera
router uses.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Dict, List, Optional, Tuple

import httpx

from services.camera.camera_mjpeg_proxy import (
    MjpegProxyError,
    credentials_for,
    ensure_streamable_content_type,
    error_message_for_status,
    redact_url,
    send_with_auth_challenge,
    split_url,
)

logger = logging.getLogger("backend.services.shared_mjpeg_proxy")


# Per-subscriber queue depth. With ``_CHUNK_BYTES = 16 KiB`` upstream
# reads this caps each slow client at ~128 KiB of buffered MJPEG
# bytes. Bounded so a single frozen tab cannot grow memory without
# bound; the drop-oldest policy (see :meth:`SharedMjpegProxy._push`)
# keeps the stream moving for everyone else.
_SUBSCRIBER_QUEUE_MAXSIZE = 8

# Mirror the upstream chunk size from the single-client proxy so the
# pump's read cadence matches what :class:`MjpegProxy` would have
# produced. Keeps memory and syscall cost equivalent to the
# single-client path.
_CHUNK_BYTES = 16 * 1024

# Idle TTL after the last subscriber releases the proxy. Matches
# the frontend's 300 ms "breath" delay + headroom so a quick reload
# reuses the socket without holding an IP-camera connection slot
# indefinitely.
_IDLE_TTL_SECONDS = 2.0

# How often the idle timer re-checks the refcount. Granularity
# trade-off — coarse enough to be cheap, fine enough that a 2 s
# TTL closes within ~100 ms of the deadline.
_IDLE_TICK_SECONDS = 0.1


class SharedMjpegProxy:
    """One upstream MJPEG connection; many downstream iterators.

    Lifecycle:

    1. ``get_or_create(url)`` on :class:`MjpegFanout` returns an
       existing proxy or instantiates a new one and ``await``s
       :meth:`start` on it. ``start`` opens the httpx connection and
       starts the pump task.
    2. Each ``/stream`` request calls :meth:`subscribe` and gets an
       async iterator + the upstream's exact ``Content-Type``.
    3. When the iterator is finalised (FastAPI body iterator cleanup)
       the caller :meth:`release`'s the subscription. The proxy's
       refcount drops; when it reaches zero the idle timer starts.
    4. 2 s later the pump is cancelled, the upstream is closed, and
       the slot is evicted from :class:`MjpegFanout`. A new request
       that arrives in the same 2 s window reuses the proxy without
       re-opening httpx.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        # Captured once on :meth:`start` so every subscriber sees the
        # upstream's exact ``Content-Type`` (including the
        # ``;boundary=...`` parameter the browser needs to parse the
        # multipart stream into frames).
        self.content_type: Optional[str] = None

        # The single upstream client/response. ``None`` until ``start``
        # succeeds; reset to ``None`` in :meth:`_tear_down`.
        self._client: Optional[httpx.AsyncClient] = None
        self._response: Optional[httpx.Response] = None

        # Per-subscriber queues. ``_subscribers`` is the source of
        # truth for refcounting; the queues are removed from it on
        # :meth:`release` and from ``_pump_task`` iteration on each
        # yield.
        self._subscribers: List["_SubscriberQueue"] = []

        # Background pump that reads from the upstream and fans chunks
        # out to every subscriber. ``None`` before ``start``, ``None``
        # again in :meth:`_tear_down`.
        self._pump_task: Optional[asyncio.Task[None]] = None

        # Idle-TTL machinery. ``_idle_handle`` is the ``call_later``
        # timer for closing the upstream; ``None`` while subscribers
        # are present.
        self._idle_handle: Optional[asyncio.TimerHandle] = None
        self._closing = False

        # Tracks whether :meth:`start` raised before any subscription was
        # ever produced. The first subscriber receives the start
        # error; subsequent subscribers see the cached error until the
        # proxy is dropped.
        self._start_error: Optional[BaseException] = None

        # Counters exposed for tests / diagnostics.
        self.upstream_read_count = 0  # number of ``aiter_bytes`` chunks read

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """Open the upstream and start the pump. Idempotent.

        Raises :class:`MjpegProxyError` on upstream 4xx / 5xx (mirrors
        :class:`MjpegProxy`), and lets :class:`httpx.HTTPError`
        subclasses propagate for the router to translate into 503s.
        """
        if self._response is not None or self._start_error is not None:
            # ``start`` was already attempted; either it succeeded or
            # it cached an error. Subscribers replay that outcome via
            # :meth:`subscribe`.
            return

        try:
            clean_url, auth = split_url(self.url)
            timeout = httpx.Timeout(
                connect=5.0,
                read=15.0,
                write=5.0,
                pool=5.0,
            )
            self._client = httpx.AsyncClient(timeout=timeout, auth=auth)
            # Credential-aware open: answers one HTTP 401 challenge
            # (Basic / Digest) using the credentials carried by the
            # URL — userinfo or query parameters. Raises
            # ``MjpegProxyError`` when the upstream demands a login
            # but the URL carries none (cached for ``subscribe``).
            self._response = await send_with_auth_challenge(
                self._client, clean_url, credentials_for(self.url)
            )

            if self._response.status_code != 200:
                # Mirror :class:`MjpegProxy`: surface a clean operator
                # hint for non-200 upstream responses. Capture the
                # status BEFORE ``_tear_down`` clears ``_response``.
                status = self._response.status_code
                detail = error_message_for_status(status)
                await self._tear_down()
                self._start_error = MjpegProxyError(
                    f"{detail} (upstream status {status})"
                )
                logger.info(
                    "SharedMjpegProxy: upstream returned %d for %s",
                    status, redact_url(clean_url),
                )
                return

            # A 200 with an HTML body is a login page, not a stream.
            ensure_streamable_content_type(self._response)

            self.content_type = (
                self._response.headers.get("content-type")
                or "multipart/x-mixed-replace"
            )
            self._pump_task = asyncio.create_task(
                self._pump(), name="shared-mjpeg-pump",
            )
            logger.info(
                "SharedMjpegProxy: opened %s (content-type=%s)",
                redact_url(clean_url), self.content_type,
            )
        except (MjpegProxyError,) as exc:
            # Cached upstream-side errors (4xx/5xx) re-raise on
            # ``subscribe``. ``get_or_create`` itself does not raise
            # so the registry can decide whether to evict and retry.
            self._start_error = exc
            await self._tear_down()
        except BaseException as exc:  # noqa: BLE001 - cache everything
            # httpx connect / timeout / network errors and any other
            # transient failure mode land here. Cache and let
            # ``subscribe`` re-raise so the caller can map to a 503
            # in the router. ``get_or_create`` itself returns a
            # proxy object whose subscription will surface the error.
            self._start_error = exc
            await self._tear_down()

    async def _pump(self) -> None:
        """Read ``aiter_bytes`` and fan each chunk to every subscriber.

        The ``await asyncio.sleep(0)`` between chunks is a fairness
        yield: with multiple subscribers a fast upstream can otherwise
        starve the consumers (Python's asyncio only reschedules other
        ready tasks on actual ``await`` suspensions, and a synthetic
        upstream that yields without suspending would never give
        the consumer tasks a chance to drain their queues).
        Real httpx ``aiter_bytes`` naturally yields on every network
        read so the cost is effectively zero in production.
        """
        try:
            assert self._response is not None  # noqa: S101 - guarded by start
            async for chunk in self._response.aiter_bytes(
                chunk_size=_CHUNK_BYTES
            ):
                self.upstream_read_count += 1
                # ``list(...)`` snapshot so ``release`` during iteration
                # cannot mutate the active list out from under us.
                for sub in list(self._subscribers):
                    sub.push(chunk)
                # Yield once per chunk so a slow subscriber's
                # ``queue.put_nowait`` overflow logic and the
                # consumer's ``queue.get`` wakes are observed by the
                # event loop in a timely fashion. Without this, a
                # synchronous synthetic upstream (the test fake) can
                # run all iterations of the pump before any consumer
                # task gets scheduled.
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            # Normal shutdown path — idle TTL or upstream error.
            raise
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.warning(
                "SharedMjpegProxy: upstream connection failed mid-stream: %s",
                exc,
            )
            # Coordinated disconnect: every subscriber's iterator exits
            # on the next yield. Avoids the thundering-herd reconnect
            # the single-client proxy used to produce.
            for sub in list(self._subscribers):
                sub.signal_end()
            # Tear the upstream down so the registry evicts the slot
            # on the next ``get_or_create``. Without this the dead
            # socket would linger until the idle TTL fires, which is
            # both wasteful and confusing for tests that assert
            # ``aclose`` semantics.
            await self._tear_down()
        except Exception as exc:  # noqa: BLE001 - last-resort logging
            logger.exception(
                "SharedMjpegProxy: pump crashed for %s: %s", self.url, exc
            )
            for sub in list(self._subscribers):
                sub.signal_end()
            await self._tear_down()
        finally:
            # Wake any subscriber stuck in ``await q.get()`` so the
            # body iterator exits cleanly on disconnect. ``signal_end``
            # is idempotent — the error-path branches above may have
            # already run.
            for sub in list(self._subscribers):
                sub.signal_end()

    async def aclose(self) -> None:
        """Tear down the upstream and the pump. Idempotent."""
        await self._tear_down()

    async def _tear_down(self) -> None:
        """Single-shot drain of upstream resources.

        Idempotent — safe to call from the idle-TTL timer, from
        :meth:`aclose`, and from the error-cleanup branch of
        :meth:`start`.
        """
        if self._pump_task is not None:
            task = self._pump_task
            self._pump_task = None
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

        if self._response is not None:
            try:
                await self._response.aclose()
            except Exception:  # noqa: BLE001 - best-effort
                logger.debug(
                    "SharedMjpegProxy: response.aclose() raised",
                    exc_info=True,
                )
            self._response = None

        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001 - best-effort
                logger.debug(
                    "SharedMjpegProxy: client.aclose() raised",
                    exc_info=True,
                )
            self._client = None

    # ------------------------------------------------------------------ #
    # Subscribe / release                                                 #
    # ------------------------------------------------------------------ #

    def subscribe(self) -> Tuple[Optional[str], "_SubscriberIterator"]:
        """Return ``(content_type, iterator)`` for a new downstream consumer.

        The first caller to subscribe is responsible for ensuring
        :meth:`start` has been awaited; the :class:`MjpegFanout`
        registry does that. Subsequent subscribers piggyback on the
        live pump.

        On upstream-start failure the cached error is re-raised here
        so the router can return a 503 with the same shape the
        single-client proxy produced. The dead slot is **evicted from
        the registry first** so the next ``get_or_create`` opens a
        fresh upstream — without this a single failure while the
        camera was unreachable would poison the slot forever (the
        registry never re-runs ``start`` on an existing entry) and
        the stream could not recover without a backend restart.
        """
        if self._start_error is not None:
            err = self._start_error
            # Evict the dead slot so a future request retries from
            # scratch, then surface the original failure.
            self._start_error = None
            self._evict_from_registry()
            raise err

        if self._response is None or self._pump_task is None:
            # Never started (or torn down) with no cached error — the
            # registry handed out a dead slot. Same recovery: evict
            # and raise a retryable error instead of returning a bogus
            # empty stream the browser would render as a silent
            # broken image.
            self._evict_from_registry()
            raise MjpegProxyError(
                "Camera stream is not running (upstream never opened). "
                "Retry the request to reconnect."
            )

        # Cancel the idle-TTL timer — at least one subscriber is now
        # live. ``call_later`` handles are cancelled by ``cancel()``.
        if self._idle_handle is not None:
            self._idle_handle.cancel()
            self._idle_handle = None

        sub = _SubscriberQueue()
        self._subscribers.append(sub)
        return self.content_type, _SubscriberIterator(sub)

    def _evict_from_registry(self) -> None:
        """Drop this proxy's registry slot (best-effort, idempotent)."""
        try:
            from services.camera.shared_mjpeg_proxy import MjpegFanout  # local import
            MjpegFanout._evict(self.url)
        except Exception:  # noqa: BLE001 - best-effort eviction
            logger.debug(
                "SharedMjpegProxy: registry evict failed", exc_info=True,
            )

    def release(self, sub: "_SubscriberQueue") -> None:
        """Drop ``sub`` from the subscriber list.

        If the resulting refcount is zero, arms the idle-TTL timer to
        tear the upstream down in 2 s. Called from the router's body
        iterator's ``finally`` block; safe to call multiple times for
        the same queue (the second call is a no-op).
        """
        try:
            self._subscribers.remove(sub)
        except ValueError:
            return  # already released
        # Wake the iterator so the body unblocks on a fast retry that
        # arrives before the pump drains.
        sub.signal_end()
        if not self._subscribers and self._idle_handle is None:
            loop = asyncio.get_event_loop()
            self._idle_handle = loop.call_later(
                _IDLE_TTL_SECONDS, self._on_idle_expire,
            )

    def _on_idle_expire(self) -> None:
        """Idle-TTL callback — tear down if still unused."""
        self._idle_handle = None
        if self._subscribers:
            # A new subscriber arrived in the 2 s window. The pump
            # is already running; nothing to do.
            return
        if self._closing:
            return
        self._closing = True
        # ``aclose`` is async but ``call_later`` callbacks are sync;
        # schedule the teardown as a task and let the event loop run
        # it. The registry's :meth:`MjpegFanout.release` evicts the
        # proxy once the task completes so a new subscriber never
        # races the close.
        loop = asyncio.get_event_loop()
        loop.create_task(self._idle_teardown())

    async def _idle_teardown(self) -> None:
        """Final close + registry eviction after idle TTL expires."""
        await self._tear_down()
        # Evict from the registry so the next ``get_or_create`` opens
        # a fresh upstream connection.
        try:
            from services.camera.shared_mjpeg_proxy import MjpegFanout  # local import
            MjpegFanout._evict(self.url)
        except Exception:  # noqa: BLE001 - best-effort eviction
            logger.debug(
                "SharedMjpegProxy: registry evict failed", exc_info=True,
            )


# ---------------------------------------------------------------------- #
# Per-subscriber queue + iterator                                         #
# ---------------------------------------------------------------------- #


class _SubscriberQueue:
    """Bounded MJPEG chunk queue with a drop-oldest overflow policy.

    ``push`` is the only writer (called from the pump task);
    ``drain`` is the only reader (called from :class:`_SubscriberIterator`).
    ``signal_end`` flips an event flag so the drain exits without
    dropping data chunks (the previous implementation pushed a
    ``None`` sentinel onto a possibly-full queue, which made room
    by evicting the OLDEST data chunk — wrong when the upstream
    ended naturally and the consumer had not yet drained).
    """

    __slots__ = ("_queue", "_ended")

    def __init__(self) -> None:
        # Bounded data queue — drop-oldest on overflow keeps memory
        # bounded even when a frozen tab's consumer is starved.
        self._queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(
            maxsize=_SUBSCRIBER_QUEUE_MAXSIZE
        )
        # End-of-stream flag. Set by ``signal_end`` so the drain
        # returns on the next pull; we deliberately avoid pushing a
        # ``None`` sentinel onto a full queue because that would
        # force-drop a real chunk to make room.
        self._ended = False

    def push(self, chunk: bytes) -> None:
        """Enqueue ``chunk`` for this subscriber; drop oldest on overflow.

        The drop-oldest policy is per-subscriber: a frozen browser tab
        loses frames but everyone else keeps streaming at full
        cadence. The MJPEG browser resyncs on the next JPEG start
        marker (``\xff\xd8``).
        """
        if self._ended:
            return
        while True:
            try:
                self._queue.put_nowait(chunk)
                return
            except asyncio.QueueFull:
                # Drop one slot to make room; the next iteration of
                # the loop tries the put again. The bounded queue
                # means this terminates within maxsize attempts.
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    # Vanishingly rare race — the consumer just
                    # drained everything. Retry the put.
                    continue

    async def drain(self) -> AsyncIterator[bytes]:
        """Yield queued chunks; exits when :meth:`signal_end` runs.

        Yield-everything semantics: every chunk that was successfully
        pushed (including the ones that survived an overflow drop)
        reaches the consumer before the iterator exits. The drain
        only returns when the upstream has signalled end-of-stream
        AND the data queue is empty.
        """
        while True:
            try:
                chunk = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                # No data right now. If the upstream has ended and
                # there's nothing left, we're done.
                if self._ended:
                    return
                # Otherwise wait for the next chunk. ``await get`` will
                # also unblock on the next ``put_nowait`` from the pump.
                chunk = await self._queue.get()
            if chunk is None:
                # Backwards-compat sentinel path — kept so any
                # ``put_nowait(None)`` from older code paths still
                # works. The current pump uses ``signal_end`` instead.
                return
            yield chunk

    def signal_end(self) -> None:
        """Mark the queue as drained; the next :meth:`drain` pull returns.

        Idempotent. Sets the ``_ended`` flag without touching the
        data queue — the consumer will see every chunk the pump
        pushed, even the LAST one. If the consumer is currently
        blocked in ``await self._queue.get()`` waiting for data
        that will never arrive (because the upstream ended and the
        queue is empty), they will block forever — so ``signal_end``
        pushes a sentinel ``None`` ONLY when the queue is empty,
        never evicting real chunks.
        """
        if self._ended:
            return
        self._ended = True
        # If the consumer is mid-await on an empty queue (e.g. they
        # connected AFTER the upstream ended), wake them with a
        # sentinel. We only push when the queue is empty so we
        # never drop a data chunk.
        if self._queue.empty():
            try:
                self._queue.put_nowait(None)
            except asyncio.QueueFull:  # pragma: no cover - bounded==empty implies !full
                pass


class _SubscriberIterator:
    """Async iterator adapter so the router can ``async for chunk in it``."""

    __slots__ = ("_queue", "_iter")

    def __init__(self, queue: _SubscriberQueue) -> None:
        self._queue = queue
        self._iter = queue.drain()

    def __aiter__(self) -> "_SubscriberIterator":
        return self

    async def __anext__(self) -> bytes:
        return await self._iter.__anext__()


# ---------------------------------------------------------------------- #
# Module-level registry                                                   #
# ---------------------------------------------------------------------- #


class MjpegFanout:
    """Refcounted ``Dict[url, SharedMjpegProxy]`` shared by the router.

    The registry is module-level so every ``/stream`` request resolves
    through the same upstream connection. ``get_or_create`` is async
    because the first caller must ``await start()`` on a freshly
    minted proxy before any other caller can subscribe.
    """

    _proxies: Dict[str, "SharedMjpegProxy"] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def get_or_create(cls, url: str) -> "SharedMjpegProxy":
        """Return the live proxy for ``url``, creating it if needed.

        The lock serialises "is there a proxy yet?" decisions so two
        concurrent first-requests cannot both instantiate and both
        open upstream connections. The first to acquire the lock
        starts the proxy; the second to acquire finds the started
        proxy and subscribes to the live pump.
        """
        async with cls._lock:
            existing = cls._proxies.get(url)
            if existing is not None:
                # The previous caller may still be inside ``start``
                # (it was awaiting httpx). Subscribing now is fine —
                # ``subscribe`` checks ``_start_error`` and either
                # returns a live iterator or replays the cached error.
                return existing

            proxy = SharedMjpegProxy(url)
            cls._proxies[url] = proxy
        # Release the lock before awaiting httpx so other subscribers
        # can pile in behind us. The fresh subscribers will see
        # ``_start_error is None`` once ``start`` completes, or
        # ``_start_error`` cached if it failed.
        await proxy.start()
        return proxy

    @classmethod
    def release(cls, url: str, sub: "_SubscriberQueue") -> None:
        """Hand a subscriber back to the proxy; may arm idle TTL."""
        proxy = cls._proxies.get(url)
        if proxy is None:
            return  # already evicted
        proxy.release(sub)

    @classmethod
    def _evict(cls, url: str) -> None:
        """Drop the proxy slot after idle teardown.

        Idempotent: if a new ``get_or_create`` already re-created the
        slot in the same window, the old proxy's eviction is a no-op.
        """
        cls._proxies.pop(url, None)

    @classmethod
    async def aclose_all(cls) -> None:
        """Tear every proxy down (lifespan shutdown).

        Drains the in-flight subscribers, cancels the pumps, closes
        every upstream connection. Used by ``stop_manager`` in the
        camera router so the backend's FastAPI lifespan exits cleanly.
        """
        async with cls._lock:
            proxies = list(cls._proxies.values())
            cls._proxies.clear()
        for proxy in proxies:
            # ``release`` arms the idle timer; cancel it first so the
            # idle teardown task does not race the explicit close.
            if proxy._idle_handle is not None:
                proxy._idle_handle.cancel()
                proxy._idle_handle = None
            await proxy.aclose()


__all__ = [
    "SharedMjpegProxy",
    "MjpegFanout",
]