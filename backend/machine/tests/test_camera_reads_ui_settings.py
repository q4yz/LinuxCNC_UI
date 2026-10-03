"""The machine backend's camera reads ``camera.*`` from the central UI
settings file by key — uncached, so a URL saved in the UI applies to
the very next request without restarting the machine backend."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.ui_settings_store import UiSettingsStore


@pytest.fixture()
def camera(tmp_path, monkeypatch):
    from routers import camera as camera_router

    monkeypatch.setattr(camera_router, "detect_usb_cameras", lambda: [])
    settings_file = tmp_path / "settings.json"
    camera_router._supervisor.use_settings_file(settings_file)
    app = FastAPI()
    app.include_router(camera_router.router)
    yield TestClient(app), UiSettingsStore(settings_file)
    camera_router._supervisor.use_settings_file(None)


def _ip_rows(client):
    return [d for d in client.get("/api/v1/modules/camera/devices").json()["devices"] if d["source"] == "ip"]


def test_unset_url_means_no_ip_camera(camera):
    client, _ = camera
    assert _ip_rows(client) == []


def test_url_changes_apply_without_restart(camera):
    client, store = camera  # the store plays the system service
    store.write_key("camera.ip_camera_url", "http://10.0.0.1/stream")
    assert [d["id"] for d in _ip_rows(client)] == ["http://10.0.0.1/stream"]

    store.write_key("camera.ip_camera_url", "http://10.0.0.2/stream")
    assert [d["id"] for d in _ip_rows(client)] == ["http://10.0.0.2/stream"]

    store.delete_key("camera.ip_camera_url")
    assert _ip_rows(client) == []


def test_default_device_is_read_by_key(camera):
    from routers import camera as camera_router

    _, store = camera
    assert camera_router._supervisor.read_default_device_id() is None
    store.write_key("camera.default_device_id", "/dev/video2")
    assert camera_router._supervisor.read_default_device_id() == "/dev/video2"


def test_a_bad_value_falls_back_to_defaults(camera):
    from routers import camera as camera_router

    _, store = camera
    store.write_key("camera.ip_camera_url", {"not": "a string"})
    # Pydantic rejects the dict; the supervisor must not crash.
    assert camera_router._supervisor.read_ip_camera_url() is None
