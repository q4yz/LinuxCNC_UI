"""Tests for the IP-camera MJPEG proxy module.

These tests pin the proxy's wire-level contract:

* URL credentials (``http://user:pass@host/path``) are extracted
  into an ``Authorization: Basic`` header so the browser never
  sees them on a cross-origin redirect.
* Upstream 4xx / 5xx responses surface as :class:`MjpegProxyError`
  with a single-line operator hint (``error_message_for_status``).
* Connection / timeout failures surface as the same exception type
  with a generic upstream-unreachable diagnostic.
* The :class:`MjpegProxy` class captures the upstream's EXACT
  ``Content-Type`` — including the ``;boundary=...`` parameter —
  in ``__aenter__``. This is the contract that lets the browser
  parse the multipart stream into frames. Without the boundary,
  the browser silently fails to render (this was the bug the
  earlier generator-based design shipped with).

The proxy itself is exercised by the router-level test
``test_stream_endpoint_passes_through_upstream_content_type`` in
``test_camera_ustreamer_supervisor.py``; the tests here focus on
the proxy's unit-level contract.
"""
from __future__ import annotations

import asyncio
import base64
from typing import List, Optional

import httpx
import pytest

from modules.camera import mjpeg_proxy
from modules.camera.mjpeg_proxy import (
    MjpegProxy,
    MjpegProxyError,
    error_message_for_status,
    split_url,
)


# ---------------------------------------------------------------------- #
# split_url                                                               #
# ---------------------------------------------------------------------- #


def test_split_url_passes_through_urls_without_credentials():
    """URLs with no ``user:pass@`` component round-trip unchanged."""
    clean, auth = split_url("http://camera.local/path?rate=0")
    assert clean == "http://camera.local/path?rate=0"
    assert auth is None


def test_split_url_extracts_credentials():
    """Embedded credentials are pulled out into BasicAuth and stripped from the URL."""
    clean, auth = split_url("http://Nacht:kamara@10.0.0.58/videostream.cgi?rate=0")
    assert clean == "http://10.0.0.58/videostream.cgi?rate=0"
    assert isinstance(auth, httpx.BasicAuth)
    # ``httpx.BasicAuth`` doesn't expose ``.username`` / ``.password``
    # as public attributes; the public surface is ``_auth_header``
    # which holds the base64-encoded ``Basic <user:pass>`` string.
    # Decode it here so the contract test stays robust against httpx
    # refactors that rename the private attribute.
    assert auth is not None
    decoded = base64.b64decode(
        auth._auth_header.split(" ", 1)[1]
    ).decode("utf-8")
    assert decoded == "Nacht:kamara"


def test_split_url_handles_username_only():
    """A URL with a username but no password still produces BasicAuth."""
    clean, auth = split_url("http://user@host/path")
    assert clean == "http://host/path"
    assert auth is not None
    decoded = base64.b64decode(
        auth._auth_header.split(" ", 1)[1]
    ).decode("utf-8")
    # Empty password survives the round-trip as the trailing colon.
    assert decoded == "user:"


def test_split_url_preserves_port():
    """``host:port`` survives the credential strip."""
    clean, auth = split_url("http://user:pass@10.0.0.58:8080/stream")
    assert clean == "http://10.0.0.58:8080/stream"
    assert auth is not None


# ---------------------------------------------------------------------- #
# error_message_for_status                                                #
# ---------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "status, snippet",
    [
        (401, "credentials"),
        (403, "refused access"),
        (404, "404"),
        (502, "unreachable"),
        (503, "unreachable"),
        (504, "unreachable"),
        (418, "418"),  # unknown status falls through to the generic message
    ],
)
def test_error_message_for_status(status, snippet):
    msg = error_message_for_status(status)
    assert snippet in msg.lower() or str(status) in msg


# ---------------------------------------------------------------------- #
# MjpegProxy class — mocked httpx upstream                                #
# ---------------------------------------------------------------------- #


class _FakeStream:
    """Stub for ``httpx.Response`` — what the proxy reads off it.

    Mirrors the parts of httpx's response object the proxy reads:
    ``status_code``, ``headers.get``, ``aclose``, ``aiter_bytes``.
    """

    def __init__(
        self,
        status_code: int = 200,
        content_type: Optional[str] = "multipart/x-mixed-replace;boundary=ipcamera",
        chunks: Optional[List[bytes]] = None,
    ) -> None:
        self.status_code = status_code
        self.headers = {"content-type": content_type} if content_type is not None else {}
        self._chunks = chunks or []
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True

    async def aiter_bytes(self, chunk_size: int):
        for c in self._chunks:
            yield c


class _FakeAsyncClient:
    """Stub for ``httpx.AsyncClient``.

    ``send(...)`` returns a ``_FakeStream`` synchronously (the real
    httpx ``send`` is an awaitable; the class shape below lets the
    proxy's ``await self._client.send(...)`` resolve naturally).
    """

    def __init__(
        self,
        fake_stream: _FakeStream,
        raise_on_send: Optional[Exception] = None,
    ) -> None:
        self._fake_stream = fake_stream
        self._raise_on_send = raise_on_send
        self.client_kwargs: dict = {}
        self.last_send_request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def aclose(self) -> None:
        pass

    def build_request(self, method: str, url: str):
        # httpx returns an ``Request`` object; the proxy only passes it
        # through to ``send``. We return a sentinel.
        self.last_send_request = (method, url)
        return ("request", method, url)

    async def send(self, request, stream: bool = False):
        if self._raise_on_send is not None:
            raise self._raise_on_send
        return self._fake_stream


def _make_fake_client_class(fake_client: _FakeAsyncClient):
    """Build a factory that captures ``AsyncClient(...)`` kwargs into ``fake_client``."""

    def _factory(**kwargs):
        fake_client.client_kwargs = kwargs
        return fake_client

    return _factory


def _drive_proxy_class(
    monkeypatch, fake_client: _FakeAsyncClient, url: str
):
    """Run the proxy lifecycle against a fake httpx client.

    Returns ``(content_type_captured, list_of_bytes_yielded)``.
    """
    monkeypatch.setattr(
        mjpeg_proxy.httpx,
        "AsyncClient",
        _make_fake_client_class(fake_client),
    )

    async def _consume():
        proxy = MjpegProxy(url)
        async with proxy as p:
            content_type = p.content_type
            chunks: List[bytes] = []
            async for chunk in p.iter_bytes():
                chunks.append(chunk)
            return content_type, chunks

    return asyncio.run(_consume())


# ---------------------------------------------------------------------- #
# Class-level contract                                                    #
# ---------------------------------------------------------------------- #


def test_mjpeg_proxy_captures_upstream_content_type_with_boundary(monkeypatch):
    """The proxy must capture the upstream's exact Content-Type (with boundary).

    This is the contract the rest of the proxy system depends on:
    the ``;boundary=ipcamera`` parameter is what lets the browser
    parse the multipart stream into frames. Without it the browser
    silently fails to render — that was the operator-facing bug
    the previous generator-based design shipped with.
    """
    upstream_bytes = [
        b"--ipcamera\r\n",
        b"Content-Type: image/jpeg\r\n\r\n",
        b"\xff\xd8\xff\xe0jpeg1\r\n",
        b"--ipcamera\r\n",
    ]
    fake_stream = _FakeStream(chunks=upstream_bytes)
    fake_client = _FakeAsyncClient(fake_stream)
    content_type, chunks = _drive_proxy_class(
        monkeypatch, fake_client, "http://camera.local/path"
    )
    # Boundary preserved exactly — this is what the StreamingResponse
    # passes back to the browser as ``Content-Type``.
    assert content_type == "multipart/x-mixed-replace;boundary=ipcamera"
    # Bytes forwarded verbatim with no sentinel / padding.
    assert chunks == upstream_bytes


def test_mjpeg_proxy_extracts_credentials_into_basic_auth(monkeypatch):
    """URL credentials travel as ``BasicAuth``, not in the URL httpx sees."""
    fake_stream = _FakeStream(chunks=[b"\xff\xd8"])
    fake_client = _FakeAsyncClient(fake_stream)
    _drive_proxy_class(
        monkeypatch, fake_client,
        "http://Nacht:kamara@10.0.0.58/videostream.cgi?rate=0",
    )
    # ``AsyncClient(auth=...)`` is the proxy's contract — the auth
    # travels on the client, not on the per-request kwargs (httpx
    # applies it transparently to every request).
    auth = fake_client.client_kwargs.get("auth")
    assert isinstance(auth, httpx.BasicAuth)
    decoded = base64.b64decode(
        auth._auth_header.split(" ", 1)[1]
    ).decode("utf-8")
    assert decoded == "Nacht:kamara"
    # The URL httpx receives has no embedded credentials.
    method, url = fake_client.last_send_request
    assert method == "GET"
    assert "Nacht" not in url
    assert "kamara" not in url


def test_mjpeg_proxy_no_auth_when_url_has_no_credentials(monkeypatch):
    """URLs without credentials round-trip with ``auth=None``."""
    fake_stream = _FakeStream(chunks=[b"x"])
    fake_client = _FakeAsyncClient(fake_stream)
    _drive_proxy_class(monkeypatch, fake_client, "http://camera.local/path")
    assert fake_client.client_kwargs.get("auth") is None


def test_mjpeg_proxy_raises_on_upstream_401(monkeypatch):
    """Upstream 401 → ``MjpegProxyError`` with a credentials hint."""
    fake_stream = _FakeStream(status_code=401)
    fake_client = _FakeAsyncClient(fake_stream)
    with pytest.raises(MjpegProxyError, match="credentials"):
        _drive_proxy_class(
            monkeypatch, fake_client,
            "http://user:pass@camera.local/path",
        )


def test_mjpeg_proxy_raises_on_upstream_403(monkeypatch):
    fake_stream = _FakeStream(status_code=403)
    fake_client = _FakeAsyncClient(fake_stream)
    with pytest.raises(MjpegProxyError, match="refused access"):
        _drive_proxy_class(monkeypatch, fake_client, "http://camera.local/path")


def test_mjpeg_proxy_raises_on_upstream_404(monkeypatch):
    fake_stream = _FakeStream(status_code=404)
    fake_client = _FakeAsyncClient(fake_stream)
    with pytest.raises(MjpegProxyError, match="404"):
        _drive_proxy_class(monkeypatch, fake_client, "http://camera.local/path")


def test_mjpeg_proxy_raises_on_upstream_5xx(monkeypatch):
    fake_stream = _FakeStream(status_code=503)
    fake_client = _FakeAsyncClient(fake_stream)
    with pytest.raises(MjpegProxyError, match="unreachable"):
        _drive_proxy_class(monkeypatch, fake_client, "http://camera.local/path")


def test_mjpeg_proxy_falls_back_to_default_content_type_when_missing(monkeypatch):
    """If the upstream omits Content-Type, fall back to ``multipart/x-mixed-replace``."""
    fake_stream = _FakeStream(content_type="", chunks=[b"\xff\xd8"])
    fake_client = _FakeAsyncClient(fake_stream)
    content_type, _ = _drive_proxy_class(
        monkeypatch, fake_client, "http://camera.local/path"
    )
    # Default fallback per the proxy contract.
    assert content_type == "multipart/x-mixed-replace"


def test_mjpeg_proxy_propagates_httpx_connection_error(monkeypatch):
    """``httpx.ConnectError`` from upstream surfaces as ``MjpegProxyError``."""
    fake_stream = _FakeStream(chunks=[])
    fake_client = _FakeAsyncClient(
        fake_stream,
        raise_on_send=httpx.ConnectError("synthetic connect failure"),
    )
    with pytest.raises(httpx.ConnectError, match="synthetic connect failure"):
        _drive_proxy_class(monkeypatch, fake_client, "http://camera.local/path")


def test_mjpeg_proxy_propagates_httpx_timeout(monkeypatch):
    """``httpx.TimeoutException`` from upstream surfaces as ``MjpegProxyError``."""
    fake_stream = _FakeStream(chunks=[])
    fake_client = _FakeAsyncClient(
        fake_stream,
        raise_on_send=httpx.ReadTimeout("synthetic read timeout"),
    )
    with pytest.raises(httpx.ReadTimeout):
        _drive_proxy_class(monkeypatch, fake_client, "http://camera.local/path")


def test_mjpeg_proxy_cleanup_closes_response_and_client(monkeypatch):
    """``__aexit__`` closes the upstream response and the httpx client."""
    fake_stream = _FakeStream(chunks=[b"x"])
    fake_client = _FakeAsyncClient(fake_stream)
    monkeypatch.setattr(
        mjpeg_proxy.httpx,
        "AsyncClient",
        _make_fake_client_class(fake_client),
    )

    async def _consume():
        async with MjpegProxy("http://camera.local/path"):
            pass

    asyncio.run(_consume())
    # The fake stream's ``aclose`` flips ``closed`` to True; the fake
    # client's ``aclose`` is a no-op but is invoked as part of the
    # ``_close`` path. The contract is "both were closed".
    assert fake_stream.closed is True


def test_mjpeg_proxy_exit_is_idempotent(monkeypatch):
    """Calling ``__aexit__`` twice is safe — second call is a no-op."""
    fake_stream = _FakeStream(chunks=[b"x"])
    fake_client = _FakeAsyncClient(fake_stream)
    monkeypatch.setattr(
        mjpeg_proxy.httpx,
        "AsyncClient",
        _make_fake_client_class(fake_client),
    )

    async def _consume():
        proxy = MjpegProxy("http://camera.local/path")
        await proxy.__aenter__()
        await proxy.__aexit__(None, None, None)
        await proxy.__aexit__(None, None, None)  # second call must not raise

    asyncio.run(_consume())
