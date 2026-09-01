"""Tests for the ``UstreamerSupervisor`` introduced in the camera
module's migration off OpenCV.

These tests pin down the on-demand subprocess lifecycle and the
operator-facing ``status()`` payload:

* one ``ustreamer`` child per device id, idempotent reuse;
* spawn failures arm a cooldown so the frontend's exponential
  backoff does not hammer a locked device;
* the ``message`` field distinguishes "dependency missing",
  "device absent", "platform unsupported", and "no devices";
* ``/stream`` returns a 503 with that message when the stream
  cannot be served, and proxied MJPEG bytes (same-origin 200)
  otherwise — for USB devices and IP-camera URLs alike.

The supervisor spawns ``ustreamer`` as a real subprocess. To keep
the test suite deterministic on hosts that do not have ``ustreamer``
installed, every test monkeypatches either
``shutil.which('ustreamer')`` or the supervisor's internal
``_spawn_locked`` helper to install a stub ``Popen``.
"""
from __future__ import annotations
from tests._module_app_factory import build_module_app

from typing import List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------- #
# Stubs                                                                   #
# ---------------------------------------------------------------------- #


class _StreamTestIter:
    """Async iterator over a fixed MJPEG body (one-shot).

    Mirrors what the router reads off a real proxy subscription: an
    async-iterable plus the ``_queue`` handle ``release`` uses to drop
    exactly this subscription on disconnect.
    """

    def __init__(self, body: bytes) -> None:
        self._body = body
        self._queue = object()  # router only reads ._queue on release

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._body is None:
            raise StopAsyncIteration
        data, self._body = self._body, None
        return data


class _FakeProc:
    """Minimal stub for :class:`subprocess.Popen`.

    Tracks ``poll()`` return value so the supervisor can tell whether
    the child is alive. Tests flip ``exit_code`` to simulate a crash.
    """

    instances: List["_FakeProc"] = []

    def __init__(
        self,
        args,
        *,
        stdout=None,
        stderr=None,
        start_new_session: bool = False,
        exit_code: int = None,
    ) -> None:
        self.args = args
        self.stdout = stdout
        self.stderr = stderr
        self.start_new_session = start_new_session
        self.returncode = exit_code
        self.terminated = False
        self.killed = False
        self.wait_count = 0
        # Fake pid; the supervisor only logs it.
        self.pid = 100000 + len(_FakeProc.instances)
        _FakeProc.instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances = []

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15  # SIGTERM

    def kill(self):
        self.killed = True
        self.returncode = -9  # SIGKILL

    def wait(self, timeout=None):
        self.wait_count += 1
        return self.returncode


@pytest.fixture()
def fake_ustreamer(monkeypatch):
    """Patch ``subprocess.Popen`` inside the camera router with a stub.

    Also resets the module-level supervisor's internal state so each
    test starts clean.
    """
    import routers.camera as router_module

    _FakeProc.reset()

    def _factory(args, **kwargs):
        # Default to "still running" so the supervisor reuses the
        # child on the second ``spawn_or_reuse`` call.
        return _FakeProc(args, exit_code=None, **kwargs)

    monkeypatch.setattr(router_module.subprocess, "Popen", _factory)

    # Wipe the supervisor's state between tests so we always start
    # with an empty process table.
    router_module._supervisor.shutdown()
    router_module._supervisor._procs.clear()
    router_module._supervisor._ports.clear()
    router_module._supervisor._cooldown_until.clear()
    return _factory


@pytest.fixture()
def fake_no_ustreamer(monkeypatch):
    """Pretend ``ustreamer`` is not on PATH; ``spawn`` raises immediately."""
    import routers.camera as router_module

    monkeypatch.setattr(router_module.shutil, "which", lambda _name: None)
    router_module._supervisor._cooldown_until.clear()


@pytest.fixture()
def fake_linux_with_devices(monkeypatch, tmp_path):
    """Pretend we are on Linux and ``/dev/video0`` exists."""
    import services.camera.camera_detection as detection
    import routers.camera as router_module

    monkeypatch.setattr(detection.sys, "platform", "linux")
    # Always report the canonical ``/dev/video0`` path so the
    # supervisor's ``known_device_ids()`` returns it — the device
    # does not actually need to exist on the test sandbox.
    monkeypatch.setattr(
        detection,
        "_list_video_device_paths",
        lambda: ["/dev/video0", "/dev/video1"],
    )
    monkeypatch.setattr(
        detection,
        "_query_v4l2_names",
        lambda _paths: {
            "/dev/video0": "Test Cam",
            "/dev/video1": "Test Cam 2",
        },
    )
    # Reset every piece of module-level state on the supervisor so
    # tests are order-independent.
    router_module._supervisor.shutdown()
    router_module._supervisor._procs.clear()
    router_module._supervisor._ports.clear()
    router_module._supervisor._cooldown_until.clear()
    return tmp_path


# ---------------------------------------------------------------------- #
# UstreamerSupervisor lifecycle                                           #
# ---------------------------------------------------------------------- #


def test_spawn_creates_one_child_per_device_id(fake_ustreamer, fake_linux_with_devices):
    from routers.camera import _supervisor

    info = _supervisor.spawn_or_reuse("/dev/video0")
    assert info["id"] == "/dev/video0"
    assert info["url"].startswith("http://127.0.0.1:")
    assert info["url"].endswith("/?action=stream")

    assert len(_supervisor._procs) == 1
    proc = _FakeProc.instances[-1]
    assert proc.args[0] == "ustreamer"
    assert "-d" in proc.args
    assert "/dev/video0" in proc.args
    assert "-p" in proc.args


def test_double_spawn_shares_child(fake_ustreamer, fake_linux_with_devices):
    from routers.camera import _supervisor

    _supervisor.spawn_or_reuse("/dev/video0")
    before = len(_FakeProc.instances)
    _supervisor.spawn_or_reuse("/dev/video0")
    after = len(_FakeProc.instances)
    assert before == after, "second spawn should reuse the live child"


def test_spawn_arms_cooldown_on_popen_failure(monkeypatch, fake_linux_with_devices):
    """If ``Popen`` raises, the cooldown blocks the next request."""
    import routers.camera as router_module
    from routers.camera import _supervisor

    def _explode(*_args, **_kwargs):
        raise OSError("synthetic spawn failure")

    monkeypatch.setattr(router_module.subprocess, "Popen", _explode)
    _supervisor._cooldown_until.clear()

    with pytest.raises(RuntimeError, match="Failed to spawn ustreamer"):
        _supervisor.spawn_or_reuse("/dev/video0")

    # Second request within cooldown must be rejected.
    with pytest.raises(RuntimeError, match="cooldown"):
        _supervisor.spawn_or_reuse("/dev/video0")


def test_shutdown_terminates_every_child(fake_ustreamer, fake_linux_with_devices):
    from routers.camera import _supervisor

    _supervisor.spawn_or_reuse("/dev/video0")
    proc = _FakeProc.instances[-1]

    _supervisor.shutdown()

    assert proc.terminated is True
    assert _supervisor._procs == {}


# ---------------------------------------------------------------------- #
# IP camera URL passthrough                                                #
# ---------------------------------------------------------------------- #


def test_spawn_returns_url_verbatim_for_http_source(
    fake_ustreamer, fake_linux_with_devices,
):
    """An ``http://…`` camera id must short-circuit to a 302 redirect.

    ustreamer cannot consume MJPEG streams over HTTP, so the
    supervisor returns the URL itself; the ``/stream`` endpoint
    issues a 302 and the browser fetches the upstream MJPEG
    directly. Crucially the URL is preserved as-is — embedded
    credentials (``http://user:pass@host/path``) survive the
    round-trip without rewriting.
    """
    from routers.camera import _supervisor

    url = "http://Nacht:kamara@10.0.0.58/videostream.cgi?rate=0"
    info = _supervisor.spawn_or_reuse(url)

    assert info["id"] == url
    assert info["url"] == url
    # No subprocess was spawned for the URL.
    assert _FakeProc.instances == [] or all(
        "ustreamer" not in (p.args or []) for p in _FakeProc.instances
    )


def test_spawn_returns_url_verbatim_for_https_and_rtsp(
    fake_ustreamer, fake_linux_with_devices,
):
    """``https://`` and ``rtsp://`` URLs are also passthrough."""
    from routers.camera import _supervisor

    for url in (
        "https://camera.example.com/stream",
        "rtsp://camera.example.com/live",
    ):
        info = _supervisor.spawn_or_reuse(url)
        assert info["id"] == url
        assert info["url"] == url


def test_status_reports_running_for_ip_camera_default(
    fake_ustreamer, fake_linux_with_devices, monkeypatch,
):
    """``status()`` reports ``running=True`` when the default device
    is an IP camera URL — there is no supervisor-managed subprocess
    for those, but the operator's UI must not show a placeholder.
    """
    from routers.camera import _supervisor

    url = "http://Nacht:kamara@10.0.0.58/videostream.cgi?rate=0"
    monkeypatch.setattr(_supervisor, "read_default_device_id", lambda: url)
    monkeypatch.setattr(_supervisor, "read_ip_camera_url", lambda: url)

    snap = _supervisor.status()
    assert snap["running"] is True
    assert snap["active_id"] == url
    assert snap["ustreamer_url"] == url
    assert snap["message"] == ""


def test_diagnostic_skips_dependency_checks_for_ip_url(
    fake_no_ustreamer, fake_linux_with_devices, monkeypatch,
):
    """An IP camera URL must not trigger the ``ustreamer``-missing
    or platform-unsupported diagnostics — the 302 redirect does not
    touch any of those dependencies.
    """
    from routers.camera import _supervisor

    url = "http://Nacht:kamara@10.0.0.58/videostream.cgi?rate=0"
    monkeypatch.setattr(_supervisor, "read_default_device_id", lambda: url)
    monkeypatch.setattr(_supervisor, "read_ip_camera_url", lambda: url)

    # ``fake_no_ustreamer`` patches ``shutil.which`` to return None
    # and the test runs on whatever the host's ``sys.platform`` is —
    # the diagnostic must still come back empty because the URL
    # bypasses every check.
    snap = _supervisor.status()
    assert snap["message"] == ""


def test_stream_endpoint_proxies_ip_camera_url(
    fake_ustreamer, fake_linux_with_devices, tmp_data_root, clean_env,
    monkeypatch,
):
    """``/stream?id=http://...`` proxies the upstream MJPEG same-origin.

    Regression guard for the HTTPS appliance: a 302 redirect pointed
    the browser at the raw ``http://`` upstream URL, which every
    browser blocks as mixed content once the SPA is served over
    HTTPS. The endpoint must stream the upstream bytes through the
    backend instead. The upstream URL — including the query-string
    credentials (``?user=...&pwd=...``) — must reach the proxy
    verbatim; the proxy forwards query parameters untouched.
    """
    import routers.camera as router_module

    expected_body = (
        b"--ipcamera\r\n"
        b"Content-Type: image/jpeg\r\n\r\n"
        b"\xff\xd8\xff\xe0jpeg\r\n"
        b"--ipcamera\r\n"
    )
    expected_content_type = "multipart/x-mixed-replace;boundary=ipcamera"

    captured_urls: list[str] = []

    class _FakeProxy:
        """Stand-in for ``SharedMjpegProxy``. Records the URL."""

        def __init__(self, url):
            captured_urls.append(url)
            self.content_type = expected_content_type

        def subscribe(self):
            return self.content_type, _StreamTestIter(expected_body)

    class _FakeFanout:
        @classmethod
        async def get_or_create(cls, url):
            return _FakeProxy(url)

        @classmethod
        def release(cls, url, sub):
            pass

    monkeypatch.setattr(router_module, "MjpegFanout", _FakeFanout)

    app = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    url = (
        "http://10.0.0.58/videostream.cgi?rate=0&user=Nacht&pwd=kamara"
    )
    # Use ``params=`` so TestClient URL-encodes the ``id`` value
    # correctly (an embedded ``&`` would otherwise be misread as a
    # query-string separator).
    resp = client.get(
        "/api/v1/modules/camera/stream",
        params={"id": url},
    )
    assert resp.status_code == 200, resp.text
    # No redirect — the response IS the proxied MJPEG body.
    assert resp.headers.get("location") is None
    # The upstream's exact content-type (with boundary) is passed
    # through — without the boundary parameter the browser cannot
    # parse the multipart stream into frames.
    assert resp.headers["content-type"] == expected_content_type
    assert b"\xff\xd8\xff\xe0jpeg" in resp.content
    # The upstream URL reached the proxy verbatim — credentials in
    # query parameters survive (the upstream needs them).
    assert captured_urls == [url]


def test_stream_endpoint_proxies_ip_camera_url_with_embedded_userinfo(
    fake_ustreamer, fake_linux_with_devices, tmp_data_root, clean_env,
    monkeypatch,
):
    """``http://user:pass@host`` URLs are proxied, not rejected.

    The proxy converts embedded userinfo into an ``Authorization``
    header server-side (conversion contract pinned in
    ``test_camera_mjpeg_proxy.py``), so the old redirect-era 503
    ("move credentials into query parameters") no longer applies —
    the endpoint must accept the URL and forward it verbatim.
    """
    import routers.camera as router_module

    captured_urls: list[str] = []

    class _FakeProxy:
        def __init__(self, url):
            captured_urls.append(url)
            self.content_type = "multipart/x-mixed-replace;boundary=x"

        def subscribe(self):
            return self.content_type, _StreamTestIter(b"")

    class _FakeFanout:
        @classmethod
        async def get_or_create(cls, url):
            return _FakeProxy(url)

        @classmethod
        def release(cls, url, sub):
            pass

    monkeypatch.setattr(router_module, "MjpegFanout", _FakeFanout)

    app = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    bad_url = "http://Nacht:kamara@10.0.0.58/videostream.cgi?rate=0"
    resp = client.get(
        "/api/v1/modules/camera/stream",
        params={"id": bad_url},
    )
    assert resp.status_code == 200, resp.text
    assert captured_urls == [bad_url]


def test_stream_endpoint_proxies_https_ip_camera_url_unchanged(
    fake_ustreamer, fake_linux_with_devices, tmp_data_root, clean_env,
    monkeypatch,
):
    """HTTPS IP camera URLs are proxied unchanged — no scheme rewrite.

    A future contributor might accidentally rewrite the scheme
    (e.g., a misguided "always downgrade to HTTP" cleanup). This
    test pins that the proxy receives whatever the operator
    configured.
    """
    import routers.camera as router_module

    captured_urls: list[str] = []

    class _FakeProxy:
        def __init__(self, url):
            captured_urls.append(url)
            self.content_type = "multipart/x-mixed-replace;boundary=x"

        def subscribe(self):
            return self.content_type, _StreamTestIter(b"")

    class _FakeFanout:
        @classmethod
        async def get_or_create(cls, url):
            return _FakeProxy(url)

        @classmethod
        def release(cls, url, sub):
            pass

    monkeypatch.setattr(router_module, "MjpegFanout", _FakeFanout)

    app = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    url = (
        "https://camera.example.com/stream?token=abc123&rate=0"
    )
    resp = client.get(
        "/api/v1/modules/camera/stream",
        params={"id": url},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("location") is None
    assert captured_urls == [url]


def test_stream_endpoint_returns_503_for_rtsp_url(
    fake_ustreamer, fake_linux_with_devices, tmp_data_root, clean_env,
):
    """RTSP URLs are not supported by the IP-camera redirect.

    ``httpx`` does not speak RTSP and the backend does not ship
    ffmpeg / gst-launch to transcode. The endpoint surfaces a
    single-line operator hint rather than crashing or hanging on a
    useless connection attempt.
    """
    app = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/modules/camera/stream?id=rtsp://camera.local/stream",
        follow_redirects=False,
    )
    assert resp.status_code == 503
    assert "RTSP" in resp.json()["detail"]


def test_stream_endpoint_proxies_usb_camera_url(
    fake_ustreamer, fake_linux_with_devices, tmp_data_root, clean_env, monkeypatch,
):
    """``/stream?id=/dev/videoN`` proxies the per-device ustreamer URL.

    Regression for the operator's setup where the supervisor spawned
    ustreamer correctly (``pid=27032`` on port 8080, ``pid=27051`` on
    port 8081 — verified in the backend logs) but ``/stream`` returned
    302 to ``http://127.0.0.1:{port}/?action=stream``. The redirect
    pointed the browser at the backend host's localhost — a URL
    unreachable from the operator's shop workstation — so the camera
    panel showed a broken image despite ustreamer being alive and
    serving MJPEG.

    The fix unifies USB cameras and IP cameras behind the
    ``MjpegFanout`` class: the backend opens a single httpx
    connection per upstream URL (not per request) and streams the
    MJPEG bytes back through a same-origin ``StreamingResponse``.

    The test pins both halves of the contract:
    1. The supervisor still returns the canonical ``http://127.0.0.1:{port}/?action=stream``
       URL (lock the URL shape so a future port-allocation refactor
       does not silently break this contract).
    2. The router calls ``MjpegFanout.get_or_create`` with that URL —
       the response is 200 OK with the upstream's MJPEG bytes and
       the upstream's exact ``Content-Type`` (boundary preserved
       verbatim).
    """
    import routers.camera as router_module

    # Synthesize what ustreamer sends. The boundary parameter is
    # whatever ustreamer's ``-d`` flag selected; the test asserts the
    # backend forwards it verbatim.
    expected_body = (
        b"--ipcamera\r\n"
        b"Content-Type: image/jpeg\r\n\r\n"
        b"\xff\xd8\xff\xe0jpeg\r\n"
        b"--ipcamera\r\n"
    )
    expected_content_type = "multipart/x-mixed-replace;boundary=ipcamera"

    captured_url: list[str] = []

    class _FakeProxy:
        """Stand-in for ``SharedMjpegProxy``. Records the URL."""

        def __init__(self, url):
            captured_url.append(url)
            self.content_type = expected_content_type

        def subscribe(self):
            return self.content_type, _FakeIter(expected_body)

    class _FakeIter:
        def __init__(self, body):
            self._body = body
            self._queue = object()  # router only reads ._queue on release

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._body is None:
                raise StopAsyncIteration
            data, self._body = self._body, None
            return data

    class _FakeFanout:
        @classmethod
        async def get_or_create(cls, url):
            return _FakeProxy(url)

        @classmethod
        def release(cls, url, sub):
            pass

    monkeypatch.setattr(router_module, "MjpegFanout", _FakeFanout)

    app = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.get("/api/v1/modules/camera/stream?id=/dev/video0")

    # Critical: NO 302 — the browser must receive the MJPEG body
    # directly from the same-origin backend.
    assert resp.status_code == 200
    assert resp.headers.get("location") is None
    # The supervisor's per-device URL is forwarded to the proxy
    # unchanged. Pin this so a future port-allocation refactor does
    # not silently break the proxy contract.
    assert captured_url == ["http://127.0.0.1:8080/?action=stream"]
    # Upstream Content-Type passes through verbatim — the boundary
    # parameter is what lets the browser parse the multipart stream.
    assert resp.headers["content-type"] == expected_content_type
    # Body bytes forwarded 1:1.
    assert resp.content == expected_body
    # Defense-in-depth cache headers.
    assert resp.headers["cache-control"] == "no-cache, no-store, must-revalidate"
    assert resp.headers["pragma"] == "no-cache"


def test_stream_endpoint_proxies_second_usb_camera(
    fake_ustreamer, fake_linux_with_devices, tmp_data_root, clean_env, monkeypatch,
):
    """``/stream?id=/dev/video1`` proxies the second per-device ustreamer URL.

    Confirms the supervisor's port allocation is deterministic across
    multiple devices: ``/dev/video0`` → port 8080, ``/dev/video1`` →
    port 8081, etc. A future refactor that re-uses ports or allocates
    dynamically would trip this test.
    """
    import routers.camera as router_module

    captured_urls: list[str] = []

    class _FakeProxy:
        def __init__(self, url):
            captured_urls.append(url)
            self.content_type = "multipart/x-mixed-replace;boundary=ipcamera"

        def subscribe(self):
            return self.content_type, _FakeIter(b"--ipcamera\r\n")

    class _FakeIter:
        def __init__(self, body):
            self._body = body
            self._queue = object()

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._body is None:
                raise StopAsyncIteration
            data, self._body = self._body, None
            return data

    class _FakeFanout:
        @classmethod
        async def get_or_create(cls, url):
            return _FakeProxy(url)

        @classmethod
        def release(cls, url, sub):
            pass

    monkeypatch.setattr(router_module, "MjpegFanout", _FakeFanout)

    app = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.get("/api/v1/modules/camera/stream?id=/dev/video1")
    assert resp.status_code == 200
    assert captured_urls == ["http://127.0.0.1:8081/?action=stream"]


def test_shutdown_is_idempotent(fake_ustreamer):
    from routers.camera import _supervisor

    # No children at all — must not raise.
    _supervisor.shutdown()
    _supervisor.shutdown()


def test_spawn_rejects_empty_id():
    from routers.camera import _supervisor

    with pytest.raises(RuntimeError, match="camera_id is required"):
        _supervisor.spawn_or_reuse("")


# ---------------------------------------------------------------------- #
# status() — diagnostic messages                                          #
# ---------------------------------------------------------------------- #


def test_status_message_reports_unsupported_platform(monkeypatch):
    """Non-Linux hosts get the platform-unsupported diagnostic."""
    import routers.camera as router_module

    monkeypatch.setattr(router_module.sys, "platform", "win32")
    snap = router_module._supervisor.status()
    assert snap["running"] is False
    assert "Linux" in snap["message"]
    assert "ustreamer" in snap["message"]


def test_status_message_reports_ustreamer_not_installed(
    fake_no_ustreamer, monkeypatch, fake_linux_with_devices,
):
    """If ``ustreamer`` is missing, status says so clearly."""
    from routers.camera import _supervisor

    monkeypatch.setattr(_supervisor, "read_default_device_id", lambda: "/dev/video0")

    snap = _supervisor.status()
    assert snap["running"] is False
    assert "ustreamer is not installed" in snap["message"]
    assert "sudo apt install ustreamer" in snap["message"]


def test_status_message_reports_no_devices(monkeypatch, fake_no_ustreamer):
    """Linux host with no ``/dev/video*`` and no IP camera → NO_DEVICES."""
    import services.camera.camera_detection as detection
    import routers.camera as router_module

    monkeypatch.setattr(detection.sys, "platform", "linux")
    monkeypatch.setattr(detection, "_list_video_device_paths", lambda: [])
    monkeypatch.setattr(router_module.shutil, "which", lambda _name: "/usr/bin/ustreamer")
    monkeypatch.setattr(
        router_module._supervisor, "read_ip_camera_url", lambda: None,
    )

    snap = router_module._supervisor.status()
    assert snap["running"] is False
    assert "No USB cameras detected" in snap["message"]


def test_status_message_reports_device_not_found(
    fake_ustreamer, fake_linux_with_devices, monkeypatch,
):
    """Configured ``default_device_id`` missing → DEVICE_NOT_FOUND."""
    import routers.camera as router_module
    from routers.camera import _supervisor

    monkeypatch.setattr(router_module.shutil, "which", lambda _name: "/usr/bin/ustreamer")
    monkeypatch.setattr(_supervisor, "read_default_device_id", lambda: "/dev/video99")
    monkeypatch.setattr(_supervisor, "read_ip_camera_url", lambda: None)

    snap = _supervisor.status()
    assert snap["running"] is False
    assert "/dev/video99" in snap["message"]
    assert "not present" in snap["message"]


def test_status_returns_running_url_when_child_alive(
    fake_ustreamer, fake_linux_with_devices, monkeypatch,
):
    """A live child → ``running=True`` with the redirect URL."""
    import routers.camera as router_module
    from routers.camera import _supervisor

    monkeypatch.setattr(router_module.shutil, "which", lambda _name: "/usr/bin/ustreamer")
    monkeypatch.setattr(_supervisor, "read_default_device_id", lambda: "/dev/video0")
    monkeypatch.setattr(_supervisor, "read_ip_camera_url", lambda: None)

    _supervisor.spawn_or_reuse("/dev/video0")
    snap = _supervisor.status()

    assert snap["running"] is True
    assert snap["active_id"] == "/dev/video0"
    assert snap["ustreamer_url"] is not None
    assert snap["ustreamer_url"].endswith("/?action=stream")
    assert snap["message"] == ""


def test_status_reports_crashed_child_exit_code(
    fake_ustreamer, fake_linux_with_devices, monkeypatch,
):
    """A child that exits non-zero → message contains the exit code."""
    import routers.camera as router_module

    monkeypatch.setattr(router_module.shutil, "which", lambda _name: "/usr/bin/ustreamer")
    monkeypatch.setattr(
        router_module._supervisor, "read_default_device_id", lambda: "/dev/video0",
    )
    monkeypatch.setattr(
        router_module._supervisor, "read_ip_camera_url", lambda: None,
    )

    router_module._supervisor.spawn_or_reuse("/dev/video0")
    _FakeProc.instances[-1].returncode = 137  # simulated crash

    snap = router_module._supervisor.status()
    assert snap["running"] is False
    assert "exited unexpectedly" in snap["message"]
    assert "137" in snap["message"]


# ---------------------------------------------------------------------- #
# /stream endpoint — 302 vs 503                                            #
# ---------------------------------------------------------------------- #


def _camera_app(tmp_data_root, clean_env) -> FastAPI:
    """Build a FastAPI app with the camera module wired up.

    Wires the camera supervisor's settings store explicitly because
    the registry no longer calls ``CameraModule.on_load`` (the
    supervisor needs the per-module SettingsStore to read
    ``default_device_id``).
    """
    from routers import camera as camera_router
    from core.settings_store import SettingsStore

    app = build_module_app("camera", tmp_data_root)
    settings = SettingsStore(
        module_id="camera",
        data_root=tmp_data_root,
        defaults=camera_router.__dict__.get("__defaults__", None)
        if False
        else None,
    )
    # Fall back to the canonical defaults class if None was passed.
    if settings._defaults is None:
        from models.camera_settings import CameraSettings
        settings._defaults = CameraSettings()
    camera_router.bind_settings_store(settings)
    return app


def test_stream_endpoint_returns_503_with_message_when_ustreamer_missing(
    fake_no_ustreamer, fake_linux_with_devices, tmp_data_root, clean_env,
):
    app = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    # Save a default device id so the endpoint does not 503 with
    # "no camera selected" — we want the dependency-missing message.
    resp = client.put(
        "/api/v1/modules/camera/settings",
        json={"default_device_id": "/dev/video0"},
    )
    assert resp.status_code == 200

    resp = client.get("/api/v1/modules/camera/stream", follow_redirects=False)
    assert resp.status_code == 503
    assert "ustreamer is not installed" in resp.json()["detail"]


def test_stream_endpoint_proxies_usb_camera_via_default_device(
    fake_ustreamer, fake_linux_with_devices, tmp_data_root, clean_env, monkeypatch,
):
    """``/stream`` (no id) proxies the configured ``default_device_id``.

    End-to-end: save ``/dev/video0`` as the default device, hit
    ``/stream`` with no id query parameter, and verify the proxy
    receives the supervisor's per-device URL. This is the path the
    frontend hits on first camera-viewer mount (no id, picks up
    the persisted default).
    """
    import routers.camera as router_module

    monkeypatch_which = __import__("pytest").MonkeyPatch()
    monkeypatch_which.setattr(
        router_module.shutil, "which", lambda _name: "/usr/bin/ustreamer"
    )

    captured_urls: list[str] = []

    class _FakeProxy:
        def __init__(self, url):
            captured_urls.append(url)
            self.content_type = "multipart/x-mixed-replace;boundary=ipcamera"

        def subscribe(self):
            return self.content_type, _FakeIter(b"--ipcamera\r\n")

    class _FakeIter:
        def __init__(self, body):
            self._body = body
            self._queue = object()

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._body is None:
                raise StopAsyncIteration
            data, self._body = self._body, None
            return data

    class _FakeFanout:
        @classmethod
        async def get_or_create(cls, url):
            return _FakeProxy(url)

        @classmethod
        def release(cls, url, sub):
            pass

    monkeypatch.setattr(router_module, "MjpegFanout", _FakeFanout)

    app = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.put(
        "/api/v1/modules/camera/settings",
        json={"default_device_id": "/dev/video0"},
    )
    assert resp.status_code == 200

    resp = client.get("/api/v1/modules/camera/stream")
    assert resp.status_code == 200
    # No 302 — the response is the proxy's MJPEG body directly.
    assert resp.headers.get("location") is None
    # The default-device-id path resolved to the supervisor's URL and
    # the router forwarded it to the proxy.
    assert captured_urls == ["http://127.0.0.1:8080/?action=stream"]
    monkeypatch_which.undo()


def test_status_endpoint_returns_message_when_dependency_missing(
    fake_no_ustreamer, fake_linux_with_devices, tmp_data_root, clean_env,
):
    app = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    client.put(
        "/api/v1/modules/camera/settings",
        json={"default_device_id": "/dev/video0"},
    )

    resp = client.get("/api/v1/modules/camera/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["running"] is False
    assert "ustreamer is not installed" in body["message"]


def test_status_endpoint_omits_message_when_healthy(
    fake_ustreamer, fake_linux_with_devices, tmp_data_root, clean_env,
):
    import routers.camera as router_module

    monkeypatch_which = __import__("pytest").MonkeyPatch()
    monkeypatch_which.setattr(
        router_module.shutil, "which", lambda _name: "/usr/bin/ustreamer"
    )

    app = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    client.put(
        "/api/v1/modules/camera/settings",
        json={"default_device_id": "/dev/video0"},
    )

    # Force the first spawn so the supervisor has a live child.
    router_module._supervisor.spawn_or_reuse("/dev/video0")

    resp = client.get("/api/v1/modules/camera/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["running"] is True
    assert body["active_id"] == "/dev/video0"
    assert body["message"] == ""
    monkeypatch_which.undo()


# ---------------------------------------------------------------------- #
# Multi-client fan-out regression                                         #
# ---------------------------------------------------------------------- #


def test_stream_endpoint_fans_out_across_concurrent_clients(
    fake_ustreamer, fake_linux_with_devices, tmp_data_root, clean_env, monkeypatch,
):
    """N concurrent ``/stream`` requests on the same URL must hit ONE proxy.

    Regression for the operator-facing bug that motivated this module:
    multiple browser tabs viewing the same camera used to open N
    separate httpx connections to the upstream (one per ``MjpegProxy``
    instance per request). IP cameras cap concurrent MJPEG clients
    at 1–3, so once the cap was hit the operator's dashboard went
    dead until every stale socket timed out — typically several
    minutes of "needs a page reload to come back".

    The fan-out proxy collapses this to a single upstream connection
    per upstream URL. Two concurrent ``/stream`` requests must end up
    sharing **one** ``SharedMjpegProxy`` and therefore one upstream
    httpx connection.
    """
    import routers.camera as router_module

    created_proxies: list = []
    subscribed_count: list = []
    registry: dict = {}

    class _TrackingProxy:
        def __init__(self, url):
            self.url = url
            self.content_type = "multipart/x-mixed-replace;boundary=ipcamera"
            created_proxies.append(self)

        def subscribe(self):
            subscribed_count.append(self.url)
            return self.content_type, _FakeIter(b"--ipcamera\r\n")

    class _FakeIter:
        def __init__(self, body):
            self._body = body
            self._queue = object()

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._body is None:
                raise StopAsyncIteration
            data, self._body = self._body, None
            return data

    class _FakeFanout:
        """Mirror the real ``MjpegFanout``'s share-within-URL contract."""

        @classmethod
        async def get_or_create(cls, url):
            if url not in registry:
                registry[url] = _TrackingProxy(url)
            return registry[url]

        @classmethod
        def release(cls, url, sub):
            pass

    monkeypatch.setattr(router_module, "MjpegFanout", _FakeFanout)

    app = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    # Fire two concurrent requests against the same URL. Each goes
    # through the router's ``_proxy_stream_response`` which now calls
    # ``MjpegFanout.get_or_create`` per request.
    resp_a = client.get("/api/v1/modules/camera/stream?id=/dev/video0")
    resp_b = client.get("/api/v1/modules/camera/stream?id=/dev/video0")

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    # Both responses carried the MJPEG body verbatim — fan-out
    # didn't change the wire contract.
    assert resp_a.content == b"--ipcamera\r\n"
    assert resp_b.content == b"--ipcamera\r\n"

    # The optimisation: only ONE proxy was instantiated, and both
    # requests subscribed to it. Pre-fan-out this list would have
    # been ``[proxy, proxy]`` (one per request).
    assert len(created_proxies) == 1, (
        f"expected 1 shared proxy, got {len(created_proxies)} — "
        f"the fan-out is regressed"
    )
    assert len(subscribed_count) == 2, (
        "both concurrent requests should have subscribed to the proxy"
    )


def test_stream_endpoint_separate_cameras_get_separate_proxies(
    fake_ustreamer, fake_linux_with_devices, tmp_data_root, clean_env, monkeypatch,
):
    """Two DIFFERENT cameras must each get their own fan-out proxy.

    Companion to the multi-client test above: the fan-out must share
    within a URL but never collapse across URLs. Two simultaneous
    requests for ``/dev/video0`` and ``/dev/video1`` produce two
    proxies — one upstream connection per camera, not one for both.
    """
    import routers.camera as router_module

    created_urls: list = []

    class _TrackingProxy:
        def __init__(self, url):
            self.url = url
            self.content_type = "multipart/x-mixed-replace;boundary=ipcamera"
            created_urls.append(url)

        def subscribe(self):
            return self.content_type, _FakeIter(b"--ipcamera\r\n")

    class _FakeIter:
        def __init__(self, body):
            self._body = body
            self._queue = object()

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._body is None:
                raise StopAsyncIteration
            data, self._body = self._body, None
            return data

    class _FakeFanout:
        @classmethod
        async def get_or_create(cls, url):
            return _TrackingProxy(url)

        @classmethod
        def release(cls, url, sub):
            pass

    monkeypatch.setattr(router_module, "MjpegFanout", _FakeFanout)

    app = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp_a = client.get("/api/v1/modules/camera/stream?id=/dev/video0")
    resp_b = client.get("/api/v1/modules/camera/stream?id=/dev/video1")

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    # Distinct URLs → distinct proxies. Pinning this guards against
    # a future refactor that "optimises" by collapsing everything
    # into a single upstream connection regardless of source.
    assert created_urls == [
        "http://127.0.0.1:8080/?action=stream",
        "http://127.0.0.1:8081/?action=stream",
    ]
