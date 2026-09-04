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
from urllib.parse import parse_qsl, parse_qs, unquote, urlparse

import httpx

logger = logging.getLogger("backend.services.camera_mjpeg_proxy")


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


#: Query-parameter key pairs operators use for camera logins, in
#: priority order. ``user``/``pwd`` is the ESP32-style convention
#: (e.g. ``videostream.cgi?user=...&pwd=...``), ``username``/
#: ``password`` the generic one.
QUERY_CREDENTIAL_KEYS: Tuple[Tuple[str, str], ...] = (
    ("user", "pwd"),
    ("username", "password"),
)

#: Flat set used by :func:`redact_url` — every key whose value must
#: never reach a log line.
_CREDENTIAL_QUERY_KEYS = {
    key for pair in QUERY_CREDENTIAL_KEYS for key in pair
}


def credentials_for(url: str) -> Optional[Tuple[str, str]]:
    """Return the best ``(user, password)`` pair carried by ``url``.

    Sources, in priority order:

    1. Embedded userinfo — ``http://user:pass@host/path`` (percent
       escapes are decoded).
    2. Query parameters — ``?user=...&pwd=...`` or
       ``?username=...&password=...``. The parameters **stay in the
       URL**; cameras that read credentials from the query string
       keep working, the pair is only lifted so the auth-challenge
       retry (:func:`send_with_auth_challenge`) can answer HTTP
       Basic / Digest logins that ignore query parameters.

    Returns ``None`` when the URL carries no usable credentials.
    """
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        return (unquote(parsed.username or ""), unquote(parsed.password or ""))
    params = parse_qs(parsed.query)
    for user_key, pwd_key in QUERY_CREDENTIAL_KEYS:
        if user_key in params and pwd_key in params:
            return (params[user_key][0], params[pwd_key][0])
    return None


def redact_url(url: str) -> str:
    """Return ``url`` safe for log lines — credentials masked.

    userinfo (``user:pass@host``) becomes ``user:***@host``; the
    values of :data:`_CREDENTIAL_QUERY_KEYS` query parameters become
    ``***``. Everything else round-trips verbatim so the log stays
    useful for debugging.
    """
    parsed = urlparse(url)

    netloc = parsed.netloc
    if parsed.username is not None or parsed.password is not None:
        host = parsed.hostname or ""
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        netloc = f"{parsed.username or ''}:***@{host}"

    query = parsed.query
    if query:
        pairs = parse_qsl(query, keep_blank_values=True)
        if any(key.lower() in _CREDENTIAL_QUERY_KEYS for key, _ in pairs):
            query = "&".join(
                f"{key}=***" if key.lower() in _CREDENTIAL_QUERY_KEYS else f"{key}={value}"
                for key, value in pairs
            )

    return parsed._replace(netloc=netloc, query=query).geturl()


async def send_with_auth_challenge(
    client: "httpx.AsyncClient",
    clean_url: str,
    credentials: Optional[Tuple[str, str]],
) -> "httpx.Response":
    """GET ``clean_url`` and answer one HTTP 401 login challenge.

    Cameras disagree on how they accept logins: some read credentials
    from query parameters (which stay in the URL verbatim), some
    challenge with HTTP Basic, some with HTTP Digest. The first
    request travels without a proxy-added ``Authorization`` header;
    on a 401 the ``WWW-Authenticate`` scheme selects the httpx auth
    implementation and the request is retried once with the best
    credentials available (:func:`credentials_for` — userinfo wins
    over query parameters).

    Returns the final (stream-mode) response — callers still owe it
    the non-200 / content-type checks.

    Raises:
        MjpegProxyError: The upstream demands a login but the URL
            carries no credentials (actionable operator hint).
        httpx.HTTPError: Connect / timeout / network failures —
            propagated for the router to translate into 503s.
    """
    request = client.build_request("GET", clean_url)
    response = await client.send(request, stream=True)
    if response.status_code != 401:
        return response

    challenge = (response.headers.get("www-authenticate") or "").strip()
    if not credentials:
        await response.aclose()
        logger.info(
            "MjpegProxy: upstream demands a login (%s) but %s carries "
            "no credentials",
            (challenge.split(";")[0][:32] or "HTTP 401"),
            redact_url(clean_url),
        )
        raise MjpegProxyError(
            "Upstream camera requires a login (HTTP 401) but the "
            "camera URL carries no credentials. Add them to the URL "
            "— ?user=...&pwd=... or http://user:pass@host/... ."
        )

    # Drain-close the challenged response before re-sending.
    await response.aclose()
    user, pwd = credentials
    if challenge.lower().startswith("digest"):
        auth = httpx.DigestAuth(user, pwd)
    else:
        # Basic challenge — or a nonstandard / absent scheme header
        # that still demands auth. Basic is the common denominator
        # and what nearly every MJPEG-capable camera implements.
        auth = httpx.BasicAuth(user, pwd)
    logger.info(
        "MjpegProxy: answering %s challenge for %s",
        (challenge.split(" ")[0] if challenge else "auth"),
        redact_url(clean_url),
    )
    retry = client.build_request("GET", clean_url)
    return await client.send(retry, stream=True, auth=auth)


def ensure_streamable_content_type(response: "httpx.Response") -> None:
    """Reject HTML responses — a login page, not an MJPEG stream.

    Some cameras answer an unauthenticated request with ``200`` plus
    the web login page instead of a 401 challenge. Streaming that
    into the browser's ``<img>`` renders a silent broken image;
    raising here surfaces the actionable hint on the supervisor's
    diagnostic panel instead.
    """
    content_type = (response.headers.get("content-type") or "").strip().lower()
    if content_type.startswith("text/html"):
        raise MjpegProxyError(
            "Upstream camera returned its login page (text/html) "
            "instead of an MJPEG stream. The camera requires "
            "authentication — add credentials to the camera URL "
            "(?user=...&pwd=... or http://user:pass@host/...)."
        )


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
        self._response = await send_with_auth_challenge(
            self._client, clean_url, credentials_for(self.url)
        )

        if self._response.status_code != 200:
            status = self._response.status_code
            detail = error_message_for_status(status)
            await self._close()
            raise MjpegProxyError(
                f"{detail} (upstream status {status})"
            )

        # A 200 with an HTML body is a login page, not a stream.
        ensure_streamable_content_type(self._response)

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
            redact_url(clean_url), self.content_type,
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
    "QUERY_CREDENTIAL_KEYS",
    "credentials_for",
    "ensure_streamable_content_type",
    "error_message_for_status",
    "redact_url",
    "send_with_auth_challenge",
    "split_url",
]
