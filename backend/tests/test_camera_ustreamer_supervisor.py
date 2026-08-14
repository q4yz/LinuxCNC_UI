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
  cannot be served, and a 302 to the per-device ``ustreamer`` URL
  otherwise.

The supervisor spawns ``ustreamer`` as a real subprocess. To keep
the test suite deterministic on hosts that do not have ``ustreamer``
installed, every test monkeypatches either
``shutil.which('ustreamer')`` or the supervisor's internal
``_spawn_locked`` helper to install a stub ``Popen``.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.module_registry import ModuleRegistry


# ---------------------------------------------------------------------- #
# Stubs                                                                   #
# ---------------------------------------------------------------------- #


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
    import modules.camera.router as router_module

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
    import modules.camera.router as router_module

    monkeypatch.setattr(router_module.shutil, "which", lambda _name: None)
    router_module._supervisor._cooldown_until.clear()


@pytest.fixture()
def fake_linux_with_devices(monkeypatch, tmp_path):
    """Pretend we are on Linux and ``/dev/video0`` exists."""
    import modules.camera.detection as detection
    import modules.camera.router as router_module

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
    from modules.camera.router import _supervisor

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
    from modules.camera.router import _supervisor

    _supervisor.spawn_or_reuse("/dev/video0")
    before = len(_FakeProc.instances)
    _supervisor.spawn_or_reuse("/dev/video0")
    after = len(_FakeProc.instances)
    assert before == after, "second spawn should reuse the live child"


def test_spawn_arms_cooldown_on_popen_failure(monkeypatch, fake_linux_with_devices):
    """If ``Popen`` raises, the cooldown blocks the next request."""
    import modules.camera.router as router_module
    from modules.camera.router import _supervisor

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
    from modules.camera.router import _supervisor

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
    from modules.camera.router import _supervisor

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
    from modules.camera.router import _supervisor

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
    from modules.camera.router import _supervisor

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
    from modules.camera.router import _supervisor

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
    fake_ustreamer, fake_linux_with_devices, tmp_data_root, clean_env, monkeypatch,
):
    """End-to-end: ``GET /stream?id=http://...`` proxies MJPEG bytes.

    Regression for the operator's URL where the browser fetched
    ``http://Nacht:kamara@10.0.0.58/videostream.cgi?rate=0`` fine but
    rendered a broken image when the backend 302-redirected to it.
    Chrome strips embedded credentials on cross-origin ``<img>``
    redirects, so the upstream returned 401 and the browser showed
    nothing.

    The fix: the backend now proxies the upstream MJPEG bytes
    one-for-one with credentials lifted into an ``Authorization``
    header. The browser sees a same-origin
    ``multipart/x-mixed-replace;boundary=...`` response with no
    credentials and renders the live stream.

    Boundary pass-through is asserted explicitly — see
    ``test_stream_endpoint_passes_through_upstream_content_type``
    below for the dedicated boundary regression.
    """
    import modules.camera.router as router_module
    from modules.camera.mjpeg_proxy import MjpegProxy

    expected_body = (
        b"--ipcamera\r\n"
        b"Content-Type: image/jpeg\r\n\r\n"
        b"\xff\xd8\xff\xe0fake-jpeg\r\n"
        b"--ipcamera\r\n"
    )

    class _FakeProxy:
        def __init__(self, url):
            self.content_type = "multipart/x-mixed-replace;boundary=ipcamera"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def iter_bytes(self):
            yield expected_body

    monkeypatch.setattr(router_module, "MjpegProxy", _FakeProxy)

    app = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    url = "http://Nacht:kamara@10.0.0.58/videostream.cgi?rate=0"
    resp = client.get(f"/api/v1/modules/camera/stream?id={url}")

    assert resp.status_code == 200
    assert "multipart/x-mixed-replace" in resp.headers["content-type"]
    # The proxy yields the synthetic bytes verbatim.
    assert expected_body in resp.content


def test_stream_endpoint_passes_through_upstream_content_type(
    fake_ustreamer, fake_linux_with_devices, tmp_data_root, clean_env, monkeypatch,
):
    """The 200 response must carry the upstream's Content-Type verbatim.

    Regression for the operator's IP camera URL where the proxy
    returned 200 OK with hard-coded ``multipart/x-mixed-replace``
    (no boundary) and the browser rendered nothing. The fix
    captures the upstream's exact ``Content-Type`` —
    ``multipart/x-mixed-replace;boundary=ipcamera`` — and uses it
    on the StreamingResponse.

    The ``;boundary=...`` parameter is what lets the browser parse
    the multipart stream into frames. Without it the browser
    silently fails to render. This test pins the boundary
    pass-through contract directly so a future contributor who
    reverts to a hard-coded ``media_type`` will trip the test
    instead of breaking the dashboard.
    """
    import modules.camera.router as router_module

    expected_boundary = "ipcamera"
    expected_content_type = (
        f"multipart/x-mixed-replace;boundary={expected_boundary}"
    )
    expected_body = (
        b"--ipcamera\r\n"
        b"Content-Type: image/jpeg\r\n\r\n"
        b"\xff\xd8\xff\xe0fake-jpeg\r\n"
        b"--ipcamera\r\n"
    )

    class _FakeProxy:
        def __init__(self, url):
            self.content_type = expected_content_type

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def iter_bytes(self):
            yield expected_body

    monkeypatch.setattr(router_module, "MjpegProxy", _FakeProxy)

    app = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    url = "http://Nacht:kamara@10.0.0.58/videostream.cgi?rate=0"
    resp = client.get(f"/api/v1/modules/camera/stream?id={url}")

    assert resp.status_code == 200
    # Critical: the upstream's exact Content-Type (with the
    # ``;boundary=...`` parameter) must reach the browser. Hard-coding
    # ``multipart/x-mixed-replace`` here is the bug this test pins.
    assert resp.headers["content-type"] == expected_content_type
    # And the body must start with the matching boundary delimiter so
    # the parser finds the first frame.
    assert resp.content.startswith(b"--ipcamera\r\n")
    # Defense-in-depth cache headers.
    assert resp.headers["cache-control"] == "no-cache, no-store, must-revalidate"
    assert resp.headers["pragma"] == "no-cache"


def test_stream_endpoint_returns_503_for_rtsp_url(
    fake_ustreamer, fake_linux_with_devices, tmp_data_root, clean_env,
):
    """RTSP URLs are not supported by the proxy module.

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


def test_shutdown_is_idempotent(fake_ustreamer):
    from modules.camera.router import _supervisor

    # No children at all — must not raise.
    _supervisor.shutdown()
    _supervisor.shutdown()


def test_spawn_rejects_empty_id():
    from modules.camera.router import _supervisor

    with pytest.raises(RuntimeError, match="camera_id is required"):
        _supervisor.spawn_or_reuse("")


# ---------------------------------------------------------------------- #
# status() — diagnostic messages                                          #
# ---------------------------------------------------------------------- #


def test_status_message_reports_unsupported_platform(monkeypatch):
    """Non-Linux hosts get the platform-unsupported diagnostic."""
    import modules.camera.router as router_module

    monkeypatch.setattr(router_module.sys, "platform", "win32")
    snap = router_module._supervisor.status()
    assert snap["running"] is False
    assert "Linux" in snap["message"]
    assert "ustreamer" in snap["message"]


def test_status_message_reports_ustreamer_not_installed(
    fake_no_ustreamer, monkeypatch, fake_linux_with_devices,
):
    """If ``ustreamer`` is missing, status says so clearly."""
    from modules.camera.router import _supervisor

    monkeypatch.setattr(_supervisor, "read_default_device_id", lambda: "/dev/video0")

    snap = _supervisor.status()
    assert snap["running"] is False
    assert "ustreamer is not installed" in snap["message"]
    assert "sudo apt install ustreamer" in snap["message"]


def test_status_message_reports_no_devices(monkeypatch, fake_no_ustreamer):
    """Linux host with no ``/dev/video*`` and no IP camera → NO_DEVICES."""
    import modules.camera.detection as detection
    import modules.camera.router as router_module

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
    import modules.camera.router as router_module
    from modules.camera.router import _supervisor

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
    import modules.camera.router as router_module
    from modules.camera.router import _supervisor

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
    import modules.camera.router as router_module

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
    from modules.camera.module import CameraModule

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, bus=EventBus(), candidates=[CameraModule()])
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


def test_stream_endpoint_returns_302_when_child_spawned(
    fake_ustreamer, fake_linux_with_devices, tmp_data_root, clean_env,
):
    import modules.camera.router as router_module

    monkeypatch_which = __import__("pytest").MonkeyPatch()
    monkeypatch_which.setattr(
        router_module.shutil, "which", lambda _name: "/usr/bin/ustreamer"
    )

    app = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.put(
        "/api/v1/modules/camera/settings",
        json={"default_device_id": "/dev/video0"},
    )
    assert resp.status_code == 200

    resp = client.get("/api/v1/modules/camera/stream", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("http://127.0.0.1:")
    assert location.endswith("/?action=stream")
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
    import modules.camera.router as router_module

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
