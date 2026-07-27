"""Tests for the camera module's per-module SettingsStore.

These tests pin down the persistence contract:

* ``GET /api/v1/modules/camera/settings`` returns the Pydantic defaults
  when no file exists yet.
* ``PUT /api/v1/modules/camera/settings`` persists atomically: no
  ``.tmp`` leftover after a crash, and the merged payload is returned.
* Single-key PUT upserts into the merged payload.
* A ``CameraWorker`` re-reads the merged settings on every frame so a
  PUT takes effect on the next captured frame without a restart.

The atomic-write property is already exercised by
``test_settings_store.py::test_atomic_write_leaves_no_partial_file_on_interrupt``;
this test verifies the *module-scoped* write behaviour, not the
underlying store.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.module_registry import ModuleRegistry
from core.settings_store import SettingsStore


def _build_app(tmp_data_root):
    """Boot a FastAPI app with the camera module mounted."""
    from modules.camera.module import CameraModule

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, bus=EventBus(), candidates=[CameraModule()])
    return app


def test_defaults_served_when_no_persisted_file(tmp_data_root: Path):
    app = _build_app(tmp_data_root)
    client = TestClient(app)

    resp = client.get("/api/v1/modules/camera/settings")
    assert resp.status_code == 200
    assert resp.json() == {
        "width": 640,
        "height": 480,
        "jpeg_quality": 70,
        "target_fps": 15,
        "default_device_id": "",
        "ip_camera_url": "",
    }

    # The store does not auto-create the file on read.
    assert not (tmp_data_root / "modules" / "camera" / "settings.json").exists()


def test_put_persists_atomically(tmp_data_root: Path):
    app = _build_app(tmp_data_root)
    client = TestClient(app)

    resp = client.put(
        "/api/v1/modules/camera/settings",
        json={"jpeg_quality": 90},
    )
    assert resp.status_code == 200
    merged = resp.json()
    assert merged["jpeg_quality"] == 90
    # Defaults survive the partial update.
    assert merged["width"] == 640

    # The file exists on disk and contains the merged payload.
    on_disk = json.loads(
        (tmp_data_root / "modules" / "camera" / "settings.json").read_text(
            encoding="utf-8",
        )
    )
    assert on_disk["jpeg_quality"] == 90
    assert on_disk["width"] == 640

    # No leftover .tmp file.
    leftovers = list(
        (tmp_data_root / "modules" / "camera").glob(".settings-*.json.tmp")
    )
    assert leftovers == []


def test_worker_reloads_settings_each_frame(tmp_data_root: Path):
    """The StreamManager reads the merged payload before every frame.

    Issue #56 replaced the background ``CameraWorker`` thread with an
    on-demand :class:`~modules.camera.router.StreamManager`. The
    public surface this test pins down is ``reload_config()``: every
    stream iteration re-reads the merged settings so a PUT takes
    effect on the next frame without a restart.
    """
    from modules.camera import router as camera_router
    from modules.camera.settings import CameraSettings

    settings = SettingsStore(
        module_id="camera",
        data_root=tmp_data_root,
        defaults=CameraSettings(),
    )

    # Wire the singleton manager to a fresh settings store — no
    # FastAPI app needed because we are not exercising HTTP.
    camera_router.bind_settings_store(settings)
    manager = camera_router._stream_manager

    cfg = manager.reload_config()
    assert cfg.jpeg_quality == 70  # defaults
    assert cfg.target_fps == 15

    # Persist a new value via the store; the manager must see it.
    settings.write_key("jpeg_quality", 95)
    cfg = manager.reload_config()
    assert cfg.jpeg_quality == 95

    # Invalid keys are silently dropped via Pydantic validation; the
    # manager falls back to defaults rather than crashing the loop.
    settings.write_all({"width": -1})  # violates ``ge=160``
    cfg = manager.reload_config()
    assert cfg.width == 640  # default still wins