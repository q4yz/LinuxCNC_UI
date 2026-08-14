"""MJPEG proxy for IP camera URLs.

The camera module previously redirected the browser to the upstream
IP camera URL via a 302. That worked in the abstract but every
mainstream browser (Chrome 86+, Firefox, Safari) strips embedded
credentials (``http://user:pass@host/path``) from cross-origin
``<img>`` redirects — a credential-leak hardening that turned our
redirect into a silent 401. The operator's upstream camera returned
``200 + multipart/x-mixed-replace`` to the original URL but ``401``
to the credential-stripped redirect, and the dashboard rendered a
broken-image glyph.

The first iteration of the proxy fix returned a ``StreamingResponse``
with a hard-coded ``media_type="multipart/x-mixed-replace"`` — which
broke the second time around because the upstream's ``Content-Type``
includes a ``;boundary=ipcamera`` parameter that the browser needs
to parse the multipart stream into frames. Without the boundary the
browser silently fails to render; with it the live MJPEG stream
displays correctly.

So this module is structured around :class:`MjpegProxy`, a class
that opens the upstream connection in ``__aenter__``, captures the
exact ``Content-Type`` synchronously, then exposes ``iter_bytes()``
for the FastAPI ``StreamingResponse`` to consume. ``StreamingResponse``
locks ``media_type`` at construction time, which is why the
content-type capture has to happen before the response object is
built — a generator-based shape (the previous design) couldn't
satisfy that ordering constraint.

Why a dedicated module (vs. inlining in router.py)?
    The router owns the endpoint surface (``/stream``, ``/devices``,
    ``/status``); the proxy owns the wire-level async streaming.
    Splitting them keeps the router's hot path (``spawn_or_reuse``,
    status diagnostics) free of httpx plumbing, and lets the proxy
    be unit-tested in isolation with a synthetic httpx client.

RTSP is intentionally rejected by the supervisor's diagnostic layer
(``rtsp://`` → 503). ``httpx`` cannot consume RTSP; converting RTSP
to MJPEG requires ffmpeg / gst-launch which is out of scope.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Optional, Tuple
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("backend.modules.camera.mjpeg_proxy")


# Cap on the upstream request so a hung IP camera cannot tie up a
# backend worker forever. The browser will reconnect on the next
# 100 ms ``<img>`` retry; we want the failure to surface fast enough
# to be visible in the supervisor's diagnostic flow.
_UPSTREAM_CONNECT_TIMEOUT_S = 5.0
_UPSTREAM_READ_TIMEOUT_S = 15.0

# Per-chunk yield size — keeps memory bounded while still being big
# enough to avoid syscall overhead on the FastAPI response loop.
_CHUNK_BYTES = 16 * 1024


class MjpegProxyError(RuntimeError):
    """Raised when the proxy cannot establish a useful upstream connection.

    The supervisor turns these into actionable 503 ``detail`` strings
    (see :func:`error_message_for_status`).
    """


def split_url(url: str) -> Tuple[str, Optional[httpx.BasicAuth]]:
    """Strip credentials out of ``url`` and return ``(clean_url, auth)``.

    ``http://user:pass@host/path`` becomes ``(http://host/path,
    BasicAuth("user", "pass"))``. The clean URL is what we pass to
    ``httpx``; the auth object is what we pass to ``httpx.AsyncClient``
    so the credentials travel in an ``Authorization`` header instead
    of the URL — keeping them out of any logs that accidentally dump
    the URL.

    URLs with no embedded credentials round-trip as-is with ``auth=None``.
    """
    parsed = urlparse(url)
    if parsed.username is None and parsed.password is None:
        return url, None
    auth = httpx.BasicAuth(parsed.username or "", parsed.password or "")
    # Rebuild the URL without the credentials. ``netloc`` carries the
    # ``host:port`` (no creds); using ``parsed._replace(netloc=...)``
    # gives us a stable URL the proxy can hand to httpx.
    host = parsed.hostname or ""
    netloc = host
    if parsed.port is not None:
        netloc = f"{host}:{parsed.port}"
    clean = parsed._replace(netloc=netloc).geturl()
    return clean, auth


def error_message_for_status(status_code: int) -> str:
    """Translate an upstream HTTP status into a single-line operator hint.

    The browser sees a 503 from the backend; the supervisor surfaces
    the upstream's actual status in the ``detail`` field so the
    operator can tell whether it's a credentials problem (401), a
    not-found problem (404), or an upstream outage (502 / 503).
    """
    if status_code == 401:
        return (
            "Upstream camera rejected the credentials. "
            "Check the username and password in the IP camera URL."
        )
    if status_code == 403:
        return (
            "Upstream camera refused access. The URL may require a "
            "different user, a token, or a source-IP allowlist."
        )
    if status_code == 404:
        return (
            "Upstream camera returned 404. The path "
            "(e.g. /videostream.cgi) may be wrong for this camera model."
        )
    if status_code in (502, 503, 504):
        return (
            "Upstream camera is unreachable. Check the network and "
            "that the camera is powered on."
        )
    return f"Upstream camera returned HTTP {status_code}."


class MjpegProxy:
    """One upstream MJPEG connection; opens once, streams bytes to one client.

    A class (not a generator) because the upstream's ``Content-Type``
    — including ``;boundary=...`` — must be captured SYNCHRONOUSLY
    before ``StreamingResponse`` is constructed. FastAPI locks
    ``media_type`` at construction time and offers no late-binding
    hook. The class opens the connection in ``__aenter__``,
    captures the content-type on the open ``Response``, then
    exposes ``iter_bytes()`` for the StreamingResponse body.

    Usage (router side)::

        proxy = MjpegProxy(url)
        try:
            await proxy.__aenter__()
        except MjpegProxyError as exc:
            raise HTTPException(503, detail=str(exc))

        return StreamingResponse(
            _wrap_with_cleanup(proxy),
            media_type=proxy.content_type,
        )

    ``__aenter__`` may raise ``MjpegProxyError`` for upstream 4xx /
    5xx responses, ``httpx.HTTPError`` subclasses for connect /
    timeout failures, and ``MjpegProxyError`` for the operator-facing
    diagnostics. The router maps each to a 503 with a single-line
    operator hint.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        self.content_type: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._response: Optional[httpx.Response] = None

    async def __aenter__(self) -> "MjpegProxy":
        clean_url, auth = split_url(self.url)
        timeout = httpx.Timeout(
            connect=_UPSTREAM_CONNECT_TIMEOUT_S,
            read=_UPSTREAM_READ_TIMEOUT_S,
            write=_UPSTREAM_CONNECT_TIMEOUT_S,
            pool=_UPSTREAM_CONNECT_TIMEOUT_S,
        )
        self._client = httpx.AsyncClient(timeout=timeout, auth=auth)
        request = self._client.build_request("GET", clean_url)
        self._response = await self._client.send(request, stream=True)

        if self._response.status_code != 200:
            status = self._response.status_code
            detail = error_message_for_status(status)
            await self._close()
            raise MjpegProxyError(
                f"{detail} (upstream status {status})"
            )

        # Capture the upstream's EXACT content-type — including
        # ``;boundary=ipcamera`` — so the browser can parse the
        # multipart stream into frames. Without it the browser
        # silently fails to render. This was the bug in the
        # earlier revision that hard-coded
        # ``media_type="multipart/x-mixed-replace"``.
        self.content_type = (
            self._response.headers.get("content-type")
            or "multipart/x-mixed-replace"
        )
        logger.info(
            "MjpegProxy: opened %s (content-type=%s)",
            clean_url, self.content_type,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        await self._close()

    async def _close(self) -> None:
        """Tear down the upstream connection and the httpx client.

        Idempotent so a caller can ``__aexit__`` twice without
        surfacing spurious exceptions (the FastAPI cleanup path
        calls ``__aexit__`` after a successful iteration and again
        when the body iterator is finalized).
        """
        if self._response is not None:
            try:
                await self._response.aclose()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                logger.debug("MjpegProxy: response.aclose() raised", exc_info=True)
            self._response = None
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001
                logger.debug("MjpegProxy: client.aclose() raised", exc_info=True)
            self._client = None

    async def iter_bytes(self) -> AsyncIterator[bytes]:
        """Yield MJPEG bytes verbatim from the open upstream response.

        Cancellation: FastAPI cancels this iterator when the client
        TCP closes. The upstream connection closes cleanly via the
        surrounding ``try / finally`` in the router's body wrapper;
        the ``MjpegProxy`` instance is reusable from ``__aenter__``
        to ``__aexit__`` exactly once per FastAPI request.
        """
        if self._response is None:
            return
        try:
            async for chunk in self._response.aiter_bytes(chunk_size=_CHUNK_BYTES):
                yield chunk
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.warning(
                "MjpegProxy: upstream connection failed mid-stream: %s", exc
            )
            raise


__all__ = [
    "MjpegProxy",
    "MjpegProxyError",
    "split_url",
    "error_message_for_status",
]
