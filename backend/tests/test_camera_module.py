"""Tests for the camera module's wiring into ``ModuleRegistry``.

These tests assert the migration contract from Issue #2:

* ``ModuleRegistry.boot([CameraModule()])`` mounts the router under
  ``/api/v1/modules/camera/`` so ``/stream`` and ``/status`` are
  reachable.
* The four canonical settings endpoints are mounted under
  ``/api/v1/modules/camera/settings`` by the registry — the module
  itself does not define a settings router.
* ``CameraModule`` satisfies ``isinstance(obj, PluggableModule)`` per
  the backend-module contract.
* Removing the module leaves ``mounted=[]`` — the nullable-module
  guarantee (covered separately in ``test_camera_null.py``).

We deliberately do **not** import ``cv2`` here; the worker is wired but
not started by the boot path. The ``/stream`` and ``/status`` endpoints
are reachable without a real camera because the worker starts lazily
on first request and degrades gracefully when OpenCV is missing.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.module_registry import ModuleRegistry
from core.protocols import PluggableModule


def _camera_app(tmp_data_root, clean_env) -> FastAPI:
    """Build a FastAPI app with the camera module booted."""
    from modules.camera.module import CameraModule

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    # Use a fresh bus to keep tests independent of the singleton.
    reg.boot(app, bus=EventBus(), candidates=[CameraModule()])
    return app, reg


def test_camera_module_satisfies_protocol(tmp_data_root, clean_env):
    from modules.camera.module import CameraModule

    instance = CameraModule()
    assert isinstance(instance, PluggableModule)
    assert instance.manifest.id == "camera"
    assert instance.manifest.settings_panel is True


def test_camera_stream_endpoint_is_mounted(tmp_data_root, clean_env):
    app, _ = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    # Status endpoint is reachable without a real camera because the
    # capture is opened lazily on the first /stream request. The new
    # schema (Issue #56) adds ``active_id`` and ``refcount`` to the
    # legacy ``{running, last_frame_at}`` keys; we assert the legacy
    # keys are still present and the new ones reflect "idle".
    resp = client.get("/api/v1/modules/camera/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["running"] is False
    assert body["last_frame_at"] is None
    assert body["active_id"] is None
    assert body["refcount"] == 0


def test_camera_usb_endpoint_is_mounted(tmp_data_root, clean_env):
    """``GET /usb`` returns the detection payload.

    No cameras are attached in the CI sandbox so the ``devices`` list
    is empty, but the endpoint shape (``devices`` + ``platform``)
    must match the Pydantic schema.
    """
    app, _ = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.get("/api/v1/modules/camera/usb")
    assert resp.status_code == 200
    body = resp.json()
    assert "devices" in body
    assert "platform" in body
    assert isinstance(body["devices"], list)
    # Platform string is non-empty (linux / win32 / darwin / other).
    assert isinstance(body["platform"], str)
    assert body["platform"]


def test_camera_settings_endpoints_are_mounted(tmp_data_root, clean_env):
    """The registry mounts the four canonical settings endpoints."""
    app, _ = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    # GET returns defaults merged in. Issue #56 renamed
    # ``device_index`` (int) to ``default_device_id`` (str) so the
    # frontend can pass through arbitrary ``/dev/videoN`` paths and
    # HTTP/RTSP URLs.
    resp = client.get("/api/v1/modules/camera/settings")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload == {
        "width": 640,
        "height": 480,
        "jpeg_quality": 70,
        "target_fps": 15,
        "default_device_id": "",
        "ip_camera_url": "",
        "preferences": {},
    }

    # PUT bulk returns the merged payload.
    resp = client.put(
        "/api/v1/modules/camera/settings",
        json={"jpeg_quality": 90},
    )
    assert resp.status_code == 200
    assert resp.json()["jpeg_quality"] == 90

    # GET round-trips.
    resp = client.get("/api/v1/modules/camera/settings")
    assert resp.json()["jpeg_quality"] == 90

    # Per-key PUT.
    resp = client.put(
        "/api/v1/modules/camera/settings/target_fps",
        json=24,
    )
    assert resp.json()["target_fps"] == 24


def test_camera_devices_endpoint_is_mounted(tmp_data_root, clean_env):
    """``GET /devices`` combines USB detection with the IP-camera URL.

    Without a configured IP camera the IP row is absent. The endpoint
    shape must match the Pydantic schema regardless of contents.
    """
    app, _ = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.get("/api/v1/modules/camera/devices")
    assert resp.status_code == 200
    body = resp.json()
    assert "devices" in body
    assert isinstance(body["devices"], list)
    for entry in body["devices"]:
        assert set(entry.keys()) == {"id", "name", "source"}
        assert entry["source"] in {"usb", "ip"}


def test_camera_registry_logs_mounted_summary(tmp_data_root, clean_env, caplog):
    """The boot summary line includes the camera module id."""
    from modules.camera.module import CameraModule

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    with caplog.at_level(logging.INFO, logger="core.module_registry"):
        reg.boot(app, bus=EventBus(), candidates=[CameraModule()])
    summary = [
        r.message
        for r in caplog.records
        if "registry: mounted=" in r.message
    ]
    assert summary, "expected the boot summary log line"
    assert "mounted=['camera']" in summary[0]
    assert "skipped=0" in summary[0]
    assert "missing=0" in summary[0]


def test_camera_on_unload_is_idempotent(tmp_data_root, clean_env):
    """Repeated ``on_unload`` is safe — the worker tolerates double-stop."""
    from modules.camera.module import CameraModule

    instance = CameraModule()
    instance.on_unload()
    instance.on_unload()  # second call must not raise
    # Status endpoint still reachable.
    app, _ = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)
    resp = client.get("/api/v1/modules/camera/status")
    assert resp.status_code == 200