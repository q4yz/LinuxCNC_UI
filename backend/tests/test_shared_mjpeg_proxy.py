"""Tests for the shared MJPEG fan-out proxy.

These tests pin the multi-client behaviour that
:class:`services.shared_mjpeg_proxy.SharedMjpegProxy` introduces:

* N concurrent subscribers hit the same upstream URL → **exactly one**
  httpx connection is opened. This is the whole point of the
  optimisation — the per-request proxy used to open one httpx
  connection per browser tab, which exhausts IP-camera connection
  caps (typically 1–3) and breaks the operator's dashboard.
* One subscriber cancels mid-stream → others keep streaming.
* Upstream errors out → all subscribers see end-of-iteration within
  one chunk; no thundering-herd reconnect.
* Slow subscriber's queue overflows → oldest chunk dropped for the
  slow subscriber only; other clients keep streaming at full cadence.
* Idle TTL: last subscriber releases the proxy → upstream stays
  open ~2 s, then closes. A new subscriber within the window reuses
  the slot.
* Content-type captured once and identical for every subscriber
  (including the ``;boundary=...`` parameter the browser needs).

The tests mock ``httpx.AsyncClient`` so the assertions run without
a real network listener. The fake upstream pushes a fixed chunk list
via a coroutine that the pump drains.
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

import pytest

from services.camera import shared_mjpeg_proxy as smp
from services.camera.shared_mjpeg_proxy import MjpegFanout
from services.camera.camera_mjpeg_proxy import MjpegProxyError


# ---------------------------------------------------------------------- #
# Fake httpx                                                               #
# ---------------------------------------------------------------------- #


class _FakeStream:
    """Stub for ``httpx.Response`` — what the proxy reads off it."""

    def __init__(
        self,
        status_code: int = 200,
        content_type: Optional[str] = (
            "multipart/x-mixed-replace;boundary=ipcamera"
        ),
        chunks: Optional[List[bytes]] = None,
        raise_after: Optional[Exception] = None,
        www_authenticate: Optional[str] = None,
    ) -> None:
        self.status_code = status_code
        headers = {}
        if content_type is not None:
            headers["content-type"] = content_type
        if www_authenticate is not None:
            headers["www-authenticate"] = www_authenticate
        self.headers = headers
        self._chunks = chunks or [b"frame-1", b"frame-2", b"frame-3"]
        self._raise_after = raise_after
        self._delivered = 0
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True

    async def aiter_bytes(self, chunk_size: int):
        for c in self._chunks:
            if self._raise_after is not None and self._delivered >= 1:
                raise self._raise_after
            self._delivered += 1
            yield c


class _FakeAsyncClient:
    """Stub for ``httpx.AsyncClient``. ``send`` returns a _FakeStream.

    Pass ``fake_streams`` (a list) to simulate a challenge flow: the
    first ``send`` pops the first entry, the retry gets the next, and
    the last entry repeats. Every call is recorded in ``send_calls``.
    """

    def __init__(
        self,
        fake_stream: _FakeStream,
        raise_on_send: Optional[Exception] = None,
        fake_streams: Optional[List[_FakeStream]] = None,
    ) -> None:
        self._fake_stream = fake_stream
        self._fake_streams = list(fake_streams) if fake_streams else None
        self._raise_on_send = raise_on_send
        self.client_kwargs: dict = {}
        self.last_send_request = None
        self.send_calls: List[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def aclose(self) -> None:
        pass

    def build_request(self, method: str, url: str):
        self.last_send_request = (method, url)
        return ("request", method, url)

    async def send(self, request, stream: bool = False, auth=None):
        self.send_calls.append({"request": request, "auth": auth})
        if self._raise_on_send is not None:
            raise self._raise_on_send
        if self._fake_streams is not None:
            if len(self._fake_streams) > 1:
                return self._fake_streams.pop(0)
            return self._fake_streams[0]
        return self._fake_stream


def _install_fake_httpx(monkeypatch, fake_client: _FakeAsyncClient):
    """Patch ``httpx.AsyncClient`` so ``SharedMjpegProxy.start`` uses it."""
    monkeypatch.setattr(
        smp.httpx,
        "AsyncClient",
        lambda **kwargs: (
            setattr(fake_client, "client_kwargs", kwargs) or fake_client
        ),
    )


# ---------------------------------------------------------------------- #
# Helpers                                                                 #
# ---------------------------------------------------------------------- #


async def _collect(iterator, max_chunks: int = 100) -> List[bytes]:
    """Pull every chunk the iterator yields, up to ``max_chunks``.

    Returns the list of chunks yielded before ``StopAsyncIteration``.
    Raises ``asyncio.TimeoutError`` if the iterator blocks past the
    test's overall timeout — keeps a hung pump from holding the
    suite forever.
    """
    out: List[bytes] = []
    while len(out) < max_chunks:
        try:
            chunk = await asyncio.wait_for(iterator.__anext__(), timeout=1.0)
            out.append(chunk)
        except (StopAsyncIteration, asyncio.TimeoutError):
            break
    return out


@pytest.fixture(autouse=True)
def _reset_registry():
    """Wipe the module-level fan-out registry between tests."""
    MjpegFanout._proxies.clear()
    yield
    MjpegFanout._proxies.clear()


# ---------------------------------------------------------------------- #
# Single-client behaviour — regression for the per-request proxy          #
# ---------------------------------------------------------------------- #


def test_single_client_yields_all_chunks(monkeypatch):
    """One subscriber sees every chunk the upstream produced."""
    fake_stream = _FakeStream(chunks=[b"a", b"b", b"c"])
    fake_client = _FakeAsyncClient(fake_stream)
    _install_fake_httpx(monkeypatch, fake_client)

    async def _run():
        proxy = await MjpegFanout.get_or_create("http://camera.local/path")
        ct, it = proxy.subscribe()
        chunks = await _collect(it)
        MjpegFanout.release("http://camera.local/path", it._queue)
        return ct, chunks

    content_type, chunks = asyncio.run(_run())
    assert content_type == "multipart/x-mixed-replace;boundary=ipcamera"
    assert chunks == [b"a", b"b", b"c"]
    # ``AsyncClient.send`` was called exactly once.
    assert fake_client.last_send_request == ("GET", "http://camera.local/path")


def test_content_type_captured_once_and_passed_to_subscriber(monkeypatch):
    """Custom Content-Type (with ``;boundary=...``) reaches the subscriber."""
    fake_stream = _FakeStream(
        content_type="multipart/x-mixed-replace;boundary=custom42",
        chunks=[b"x"],
    )
    fake_client = _FakeAsyncClient(fake_stream)
    _install_fake_httpx(monkeypatch, fake_client)

    async def _run():
        proxy = await MjpegFanout.get_or_create("http://camera.local/path")
        ct, _ = proxy.subscribe()
        return ct

    assert asyncio.run(_run()) == "multipart/x-mixed-replace;boundary=custom42"


def test_default_content_type_when_missing(monkeypatch):
    """Upstream omits ``Content-Type`` → fall back to ``multipart/x-mixed-replace``."""
    fake_stream = _FakeStream(content_type="", chunks=[b"x"])
    fake_client = _FakeAsyncClient(fake_stream)
    _install_fake_httpx(monkeypatch, fake_client)

    async def _run():
        proxy = await MjpegFanout.get_or_create("http://camera.local/path")
        ct, _ = proxy.subscribe()
        return ct

    assert asyncio.run(_run()) == "multipart/x-mixed-replace"


# ---------------------------------------------------------------------- #
# Multi-client behaviour — the whole point of the optimisation             #
# ---------------------------------------------------------------------- #


def test_five_concurrent_subscribers_share_one_upstream(monkeypatch):
    """N=5 concurrent subscribers → exactly **one** httpx send call.

    The per-request proxy used to issue one ``send`` per browser
    tab; with N tabs and IP-camera caps of 1–3, the operator's
    dashboard started refusing connections. The shared proxy
    collapses this to a single upstream connection.
    """
    fake_stream = _FakeStream(
        chunks=[b"f1", b"f2", b"f3", b"f4", b"f5", b"f6"],
    )
    fake_client = _FakeAsyncClient(fake_stream)

    # Track every time ``send`` is called. The pump task is what
    # drives sends — we assert only one fires across the entire
    # lifecycle regardless of how many subscribers pile in.
    send_calls: List[tuple] = []

    real_send = fake_client.send

    async def _tracked_send(*args, **kwargs):
        send_calls.append(args)
        return await real_send(*args, **kwargs)

    fake_client.send = _tracked_send  # type: ignore[assignment]
    _install_fake_httpx(monkeypatch, fake_client)

    async def _run():
        proxy = await MjpegFanout.get_or_create("http://camera.local/path")
        iterators = []
        for _ in range(5):
            _, it = proxy.subscribe()
            iterators.append(it)
        # Give the pump a moment to drain.
        await asyncio.sleep(0.05)
        per_client = []
        for it in iterators:
            chunks = await _collect(it, max_chunks=6)
            per_client.append(chunks)
            MjpegFanout.release("http://camera.local/path", it._queue)
        return per_client, send_calls

    per_client, send_calls = asyncio.run(_run())

    # Every subscriber saw the same chunks — the fan-out is identical.
    assert per_client == [[b"f1", b"f2", b"f3", b"f4", b"f5", b"f6"]] * 5
    # Exactly one upstream ``send`` for five concurrent clients.
    assert len(send_calls) == 1, (
        f"expected single upstream connection, got {len(send_calls)}"
    )


def test_one_subscriber_cancels_others_keep_streaming(monkeypatch):
    """One subscriber's iterator exits early → others keep yielding.

    Simulates the operator closing one of two browser tabs mid-stream.
    The remaining tab must not lose frames; the upstream must not be
    torn down just because one subscriber left (a second subscriber
    is still attached).
    """
    fake_stream = _FakeStream(
        chunks=[b"a", b"b", b"c", b"d", b"e", b"f"],
    )
    fake_client = _FakeAsyncClient(fake_stream)
    _install_fake_httpx(monkeypatch, fake_client)

    async def _run():
        proxy = await MjpegFanout.get_or_create("http://camera.local/path")
        ct1, it1 = proxy.subscribe()
        ct2, it2 = proxy.subscribe()
        # Cancel subscriber 1 after the first chunk.
        first1 = await it1.__anext__()
        assert first1 == b"a"
        MjpegFanout.release("http://camera.local/path", it1._queue)
        # Subscriber 2 keeps going.
        rest = await _collect(it2, max_chunks=6)
        MjpegFanout.release("http://camera.local/path", it2._queue)
        return rest

    assert asyncio.run(_run()) == [b"a", b"b", b"c", b"d", b"e", b"f"]


def test_upstream_error_closes_every_subscriber_within_one_chunk(monkeypatch):
    """Upstream ``httpx.ConnectError`` mid-stream → all subs exit fast.

    Without the fan-out, each subscriber would independently
    reconnect on the error, piling more requests on a dying
    upstream. With the fan-out, the pump signals end-of-iteration
    to every subscriber so they reconnect in lockstep (the frontend
    already has the exponential backoff in ``CameraViewer.vue``).
    """
    fake_stream = _FakeStream(
        chunks=[b"a", b"b", b"c"],
        raise_after=__import__("httpx").ConnectError("synthetic upstream fail"),
    )
    fake_client = _FakeAsyncClient(fake_stream)
    _install_fake_httpx(monkeypatch, fake_client)

    async def _run():
        proxy = await MjpegFanout.get_or_create("http://camera.local/path")
        iters = []
        for _ in range(3):
            _, it = proxy.subscribe()
            iters.append(it)
        # Give the pump a moment to reach the error.
        await asyncio.sleep(0.1)
        out = []
        for it in iters:
            out.append(await _collect(it))
            MjpegFanout.release("http://camera.local/path", it._queue)
        return out

    per_sub = asyncio.run(_run())
    # Each subscriber saw at least one chunk (the ones read before the
    # error fired) and then StopAsyncIteration. None of them should
    # have got the full chunk list — the pump raised after one read.
    for chunks in per_sub:
        assert len(chunks) >= 1
        assert len(chunks) < 3
    # Cleanup: pump should have closed the response.
    assert fake_stream.closed is True


# ---------------------------------------------------------------------- #
# Slow-subscriber policy — drop oldest for the slow client only           #
# ---------------------------------------------------------------------- #


def test_slow_subscriber_drops_oldest_others_unaffected(monkeypatch):
    """A frozen tab's overflow drops its own oldest chunks.

    The pump keeps reading from upstream at full cadence; the fast
    subscribers see every chunk; the slow subscriber's queue stays
    bounded because push() drops its oldest queued chunk on overflow.

    Production scenario: the operator has 2 browser tabs on the same
    camera; one is active (actively rendering frames, draining the
    per-subscriber queue), the other is backgrounded (consumer
    throttled). The pump should keep the active tab at full cadence
    and only the backgrounded tab should drop frames.

    The test simulates this by running the fast-drain as a sibling
    task alongside the pump, started before chunks 1..N are pushed.
    """
    # 16 chunks × 1 KiB pushes against maxsize=8 queue.
    fake_stream = _FakeStream(
        chunks=[bytes([i]) * 1024 for i in range(16)],
    )
    fake_client = _FakeAsyncClient(fake_stream)
    _install_fake_httpx(monkeypatch, fake_client)

    async def _drain_into_list(it):
        out = []
        while True:
            try:
                out.append(await asyncio.wait_for(it.__anext__(), timeout=3.0))
            except (StopAsyncIteration, asyncio.TimeoutError):
                break
        return out

    async def _run():
        url = "http://camera.local/path"
        proxy = await MjpegFanout.get_or_create(url)
        _, slow = proxy.subscribe()
        _, fast = proxy.subscribe()
        # Run the fast drain CONCURRENTLY with the pump. The slow
        # subscriber is left untouched — its queue fills and overflows.
        fast_task = asyncio.create_task(_drain_into_list(fast))
        # Yield once so the pump + drain have a chance to make progress
        # together (without this the pump drains the upstream into the
        # bounded fast queue before the drain task gets scheduled).
        await asyncio.sleep(0)
        fast_chunks = await fast_task
        slow_chunks = await _drain_into_list(slow)
        MjpegFanout.release(url, slow._queue)
        MjpegFanout.release(url, fast._queue)
        return fast_chunks, slow_chunks

    fast_chunks, slow_chunks = asyncio.run(_run())
    # Fast subscriber saw every upstream chunk (16) — the active
    # consumer kept pace with the pump's push cadence.
    assert len(fast_chunks) == 16, (
        f"fast subscriber lost frames: got {len(fast_chunks)}"
    )
    assert fast_chunks == [bytes([i]) * 1024 for i in range(16)]
    # Slow subscriber's queue is bounded — at most maxsize=8 chunks
    # remain when it eventually drains, and the contents are the
    # *newest* chunks (drop-oldest policy).
    assert 1 <= len(slow_chunks) <= 8
    # The slow subscriber's oldest surviving chunk must be at least
    # the 9th byte-of-1KiB chunk (chunks 0..7 are the dropped oldest).
    assert slow_chunks[0][0] >= 8


# ---------------------------------------------------------------------- #
# Idle TTL — keep-alive for a quick reload, close when truly idle         #
# ---------------------------------------------------------------------- #


def test_idle_ttl_closes_upstream_after_last_release(monkeypatch):
    """Last subscriber releases → upstream stays open ~2 s, then closes.

    Without an idle TTL the upstream connection would either never
    close (tying up an IP-camera slot forever) or close immediately
    on the last release (forcing a full reconnect on the next
    reload). The 2 s window mirrors the frontend's 300 ms breath
    delay + headroom so a quick reload reuses the slot.
    """
    fake_stream = _FakeStream(chunks=[b"a"])
    fake_client = _FakeAsyncClient(fake_stream)
    _install_fake_httpx(monkeypatch, fake_client)

    async def _run():
        proxy = await MjpegFanout.get_or_create("http://camera.local/path")
        _, it = proxy.subscribe()
        await _collect(it)
        MjpegFanout.release("http://camera.local/path", it._queue)
        # Upstream must NOT be closed yet — idle TTL is armed but
        # not yet expired.
        assert fake_stream.closed is False
        # Wait past the 2 s TTL for the close to fire. The pump has
        # nothing left to read so it ends on its own; the idle timer
        # then tears the upstream down.
        for _ in range(40):
            await asyncio.sleep(0.1)
            if fake_stream.closed:
                break
        return fake_stream.closed

    # We bound the wait at ~4 s. The idle TTL is 2 s, so the close
    # fires well within that window. ``aclose_all`` is the
    # synchronous cleanup path; ``_idle_teardown`` runs as a task
    # that the event loop drains within the wait.
    assert asyncio.run(_run()) is True


def test_new_subscriber_within_idle_window_reuses_proxy(monkeypatch):
    """A subscriber that arrives within 2 s of the last release reuses
    the slot — no second ``send`` is issued.

    The fake upstream keeps yielding forever (looping ``aiter_bytes``)
    so the pump stays alive after the first subscriber releases, and
    the second subscriber can see chunks from the same upstream
    connection rather than reopening httpx.
    """
    send_calls: List[tuple] = []

    class _LoopingStream(_FakeStream):
        """``aiter_bytes`` keeps cycling through the chunk list."""

        async def aiter_bytes(self, chunk_size):
            i = 0
            while True:
                yield bytes([i]) * 4
                i += 1

    fake_stream = _LoopingStream(chunks=[])
    fake_client = _FakeAsyncClient(fake_stream)

    real_send = fake_client.send

    async def _tracked_send(*args, **kwargs):
        send_calls.append(args)
        return await real_send(*args, **kwargs)

    fake_client.send = _tracked_send  # type: ignore[assignment]
    _install_fake_httpx(monkeypatch, fake_client)

    async def _run():
        url = "http://camera.local/path"
        proxy1 = await MjpegFanout.get_or_create(url)
        _, it1 = proxy1.subscribe()
        # Pull just enough to register the subscriber; don't drain
        # the upstream.
        first = await asyncio.wait_for(it1.__anext__(), timeout=2.0)
        MjpegFanout.release(url, it1._queue)
        # Immediately request a fresh subscriber on the same URL —
        # well within the 2 s idle window. The registry should hand
        # back the same proxy and NOT issue a second httpx send.
        proxy2 = await MjpegFanout.get_or_create(url)
        _, it2 = proxy2.subscribe()
        # Pull one chunk from the second subscriber to confirm the
        # upstream is still alive and shared.
        second = await asyncio.wait_for(it2.__anext__(), timeout=2.0)
        MjpegFanout.release(url, it2._queue)
        # Clean up the looping upstream so the test process exits.
        await MjpegFanout.aclose_all()
        return proxy1 is proxy2, first, second

    same_proxy, first, second = asyncio.run(_run())
    assert same_proxy is True, "registry should reuse the slot within idle TTL"
    assert len(send_calls) == 1, "no second upstream connection should open"
    # Both subscribers received chunks from the SAME upstream — the
    # first from index 0, the second from a later index.
    assert first == bytes([0]) * 4
    assert second != first  # pump kept running between the two subscriptions


# ---------------------------------------------------------------------- #
# Start errors — first caller surfaces, subsequent callers replay         #
# ---------------------------------------------------------------------- #


def test_start_error_surfaces_to_first_subscriber(monkeypatch):
    """If httpx cannot connect, the first subscriber sees ``ConnectError``."""
    fake_client = _FakeAsyncClient(
        _FakeStream(),
        raise_on_send=__import__("httpx").ConnectError("synthetic connect fail"),
    )
    _install_fake_httpx(monkeypatch, fake_client)

    async def _run():
        # ``get_or_create`` swallows ``ConnectError`` into the cache
        # and re-raises on ``subscribe`` — the router catches it via
        # the same ``except httpx.ConnectError`` handler as the
        # single-client proxy.
        proxy = await MjpegFanout.get_or_create("http://camera.local/path")
        try:
            proxy.subscribe()
            return "no-error"
        except __import__("httpx").ConnectError:
            return "ConnectError"

    assert asyncio.run(_run()) == "ConnectError"


def test_upstream_4xx_surfaces_as_mjpeg_proxy_error(monkeypatch):
    """Upstream 401 → ``MjpegProxyError`` on subscribe."""
    fake_stream = _FakeStream(status_code=401)
    fake_client = _FakeAsyncClient(fake_stream)
    _install_fake_httpx(monkeypatch, fake_client)

    async def _run():
        proxy = await MjpegFanout.get_or_create("http://camera.local/path")
        try:
            proxy.subscribe()
            return "no-error"
        except MjpegProxyError as exc:
            return str(exc)

    msg = asyncio.run(_run())
    assert "401" in msg


def test_upstream_digest_challenge_is_answered_with_query_credentials(
    monkeypatch,
):
    """``start()`` answers a Digest 401 using ``?user=...&pwd=...`` creds.

    The camera's login is handled server-side by the proxy: the first
    request is challenged, the retry carries ``httpx.DigestAuth``
    built from the query-parameter credentials, and the stream opens.
    The credentials stay in the URL for cameras that read them there.
    """
    fake_client = _FakeAsyncClient(
        None,
        fake_streams=[
            _FakeStream(
                status_code=401,
                www_authenticate='Digest realm="ipcamera", nonce="abc"',
            ),
            _FakeStream(
                status_code=200,
                content_type="multipart/x-mixed-replace;boundary=ipcamera",
                chunks=[b"a", b"b"],
            ),
        ],
    )
    _install_fake_httpx(monkeypatch, fake_client)

    async def _run():
        proxy = await MjpegFanout.get_or_create(
            "http://10.0.0.58/videostream.cgi?rate=0&user=Nacht&pwd=kamara"
        )
        ct, it = proxy.subscribe()
        chunks = await _collect(it)
        return ct, chunks

    content_type, chunks = asyncio.run(_run())
    assert content_type == "multipart/x-mixed-replace;boundary=ipcamera"
    assert chunks == [b"a", b"b"]
    # Challenge + authenticated retry.
    assert len(fake_client.send_calls) == 2
    import httpx as _httpx

    assert isinstance(fake_client.send_calls[1]["auth"], _httpx.DigestAuth)
    # Both requests keep the credentials in the query string.
    for call in fake_client.send_calls:
        assert "user=Nacht" in call["request"][2]
        assert "pwd=kamara" in call["request"][2]


def test_upstream_html_login_page_surfaces_as_mjpeg_proxy_error(monkeypatch):
    """200 + ``text/html`` is a login page — actionable error, not a stream."""
    fake_stream = _FakeStream(status_code=200, content_type="text/html")
    fake_client = _FakeAsyncClient(fake_stream)
    _install_fake_httpx(monkeypatch, fake_client)

    async def _run():
        proxy = await MjpegFanout.get_or_create("http://camera.local/login")
        try:
            proxy.subscribe()
            return "no-error"
        except MjpegProxyError as exc:
            return str(exc)

    msg = asyncio.run(_run())
    assert "login page" in msg


# ---------------------------------------------------------------------- #
# Idempotency                                                              #
# ---------------------------------------------------------------------- #


def test_release_is_idempotent(monkeypatch):
    """Calling ``release`` twice for the same subscription is a no-op."""
    fake_stream = _FakeStream(chunks=[b"a"])
    fake_client = _FakeAsyncClient(fake_stream)
    _install_fake_httpx(monkeypatch, fake_client)

    async def _run():
        url = "http://camera.local/path"
        proxy = await MjpegFanout.get_or_create(url)
        _, it = proxy.subscribe()
        await _collect(it)
        MjpegFanout.release(url, it._queue)
        # Second release on the same queue must not raise and must
        # not over-decrement the refcount.
        MjpegFanout.release(url, it._queue)
        # The proxy slot is still there with refcount zero; the idle
        # timer is armed.
        return url in MjpegFanout._proxies

    assert asyncio.run(_run()) is True


# ---------------------------------------------------------------------- #
# Cleanup contract — lifespan shutdown drains every proxy                 #
# ---------------------------------------------------------------------- #


def test_aclose_all_drains_every_proxy(monkeypatch):
    """``MjpegFanout.aclose_all`` closes every still-live proxy."""
    streams = []
    clients = []
    url_to_client: dict = {}

    for i in range(3):
        stream = _FakeStream(chunks=[b"x"])
        client = _FakeAsyncClient(stream)
        streams.append(stream)
        clients.append(client)
        url_to_client[f"http://camera.local/{i}"] = client

    # Single ``AsyncClient`` factory that dispatches by URL — the
    # test's three proxies need three distinct upstream connections
    # so the post-close assertions can identify which stream was
    # bound to which URL.
    def _factory(**kwargs):
        url = kwargs.get("auth")  # placeholder — see below
        # ``build_request`` already captured the URL on the client;
        # the factory just returns the right client for the URL.
        # We rely on the test ordering to assign one client per URL.
        return clients[len(url_to_client) - len(urls_to_open)]

    urls_to_open = list(url_to_client.keys())

    def _dispatching_factory(**kwargs):
        # Round-robin through the remaining URLs in test order.
        client = url_to_client[urls_to_open[0]]
        urls_to_open.pop(0)
        client.client_kwargs = kwargs
        return client

    monkeypatch.setattr(
        smp.httpx,
        "AsyncClient",
        _dispatching_factory,
    )

    async def _run():
        iterators = []
        for url in url_to_client:
            proxy = await MjpegFanout.get_or_create(url)
            _, it = proxy.subscribe()
            iterators.append((url, it))
        await MjpegFanout.aclose_all()
        # Every upstream response was closed.
        for stream in streams:
            assert stream.closed is True, (
                "every proxy's upstream must be closed after aclose_all"
            )
        # Registry was wiped.
        return dict(MjpegFanout._proxies)

    remaining = asyncio.run(_run())
    assert remaining == {}


def test_credentials_extracted_into_basic_auth(monkeypatch):
    """Embedded ``user:pass@host`` travels as ``BasicAuth``, not in URL."""
    fake_stream = _FakeStream(chunks=[b"x"])
    fake_client = _FakeAsyncClient(fake_stream)
    _install_fake_httpx(monkeypatch, fake_client)

    async def _run():
        proxy = await MjpegFanout.get_or_create(
            "http://Nacht:kamara@camera.local/path"
        )
        proxy.subscribe()
        return fake_client.client_kwargs

    import httpx
    kwargs = asyncio.run(_run())
    assert isinstance(kwargs.get("auth"), httpx.BasicAuth)
    assert "Nacht" not in fake_client.last_send_request[1]
    assert "kamara" not in fake_client.last_send_request[1]