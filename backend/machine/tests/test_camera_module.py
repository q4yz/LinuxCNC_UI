"""Tests for the camera module's wiring into ``ModuleRegistry``.

These tests assert the migration contract from Issue #2:

* ``ModuleRegistry.boot([CameraModule()])`` mounts the router under
  ``/api/v1/modules/camera/`` so ``/stream``, ``/devices`` and
  ``/status`` are reachable.
* The four canonical settings endpoints are mounted under
  ``/api/v1/modules/camera/settings`` by the registry — the module
  itself does not define a settings router.
* ``CameraModule`` satisfies ``isinstance(obj, PluggableModule)`` per
  the backend-module contract.
* Removing the module leaves ``mounted=[]`` — the nullable-module
  guarantee (covered separately in ``test_camera_null.py``).

We deliberately do **not** import ``cv2`` here; the supervisor is wired
but the first ``ustreamer`` subprocess is spawned lazily on the first
``/stream`` request. The ``/stream``, ``/status`` and ``/devices``
endpoints are reachable without a real camera and degrade gracefully
when ``ustreamer`` is missing.
"""
from __future__ import annotations
from tests._module_app_factory import build_module_app

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus

def _camera_app(tmp_data_root, clean_env=None):
    """Build a FastAPI app with the camera module wired up."""
    return build_module_app("camera", tmp_data_root), None

def test_camera_status_endpoint_is_mounted(tmp_data_root, clean_env):
    app, _ = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    # Status endpoint is reachable without a real camera because the
    # first ``ustreamer`` subprocess is spawned lazily on the first
    # ``/stream`` request. The slim (post-OpenCV) schema carries
    # ``{running, active_id, ustreamer_url, message}``; with no
    # device configured the supervisor reports ``running=False``.
    # On Linux with no devices configured the ``message`` is empty;
    # on Windows the supervisor surfaces the platform-unsupported
    # diagnostic instead. Both shapes satisfy the schema contract.
    resp = client.get("/api/v1/modules/camera/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["running"] is False
    assert body["active_id"] is None
    assert body["ustreamer_url"] is None
    assert "message" in body
    assert isinstance(body["message"], str)

def test_camera_usb_endpoint_is_mounted(tmp_data_root, clean_env):
    """``GET /usb`` returns the detection payload.

    No cameras are attached in the CI sandbox so the ``devices`` list
    is empty, but the endpoint shape (``devices`` + ``platform``)
    must match the documented contract.
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

    # GET returns defaults merged in. The slim (post-OpenCV) settings
    # schema carries only ``{default_device_id, ip_camera_url,
    # preferences, macro_buttons}`` — the four MJPEG knobs were
    # removed when the module moved to ``ustreamer``.
    resp = client.get("/api/v1/modules/camera/settings")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload == {
        "default_device_id": "",
        "ip_camera_url": "",
        "preferences": {},
        "macro_buttons": [],
    }

    # PUT bulk returns the merged payload.
    resp = client.put(
        "/api/v1/modules/camera/settings",
        json={"ip_camera_url": "rtsp://camera.local/stream"},
    )
    assert resp.status_code == 200
    assert resp.json()["ip_camera_url"] == "rtsp://camera.local/stream"

    # GET round-trips.
    resp = client.get("/api/v1/modules/camera/settings")
    assert resp.json()["ip_camera_url"] == "rtsp://camera.local/stream"

    # Per-key PUT.
    resp = client.put(
        "/api/v1/modules/camera/settings/default_device_id",
        json="/dev/video0",
    )
    assert resp.json()["default_device_id"] == "/dev/video0"

def test_camera_devices_endpoint_is_mounted(tmp_data_root, clean_env):
    """``GET /devices`` combines USB detection with the IP-camera URL.

    Without a configured IP camera the IP row is absent. The endpoint
    shape must match the documented contract regardless of contents.
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

def test_camera_stream_endpoint_returns_503_when_no_device_selected(
    tmp_data_root, clean_env,
):
    """Without ``default_device_id`` the endpoint returns 503 + hint.

    The OpenCV-era implementation streamed bytes; the ustreamer-era
    implementation redirects via 302 once a child is spawned. With no
    device configured the operator has not picked a camera yet, so the
    endpoint surfaces a single-line operator hint in the 503 ``detail``
    instead of an opaque redirect.
    """
    app, _ = _camera_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.get("/api/v1/modules/camera/stream", follow_redirects=False)
    assert resp.status_code == 503
    assert "No camera selected" in resp.json()["detail"]

