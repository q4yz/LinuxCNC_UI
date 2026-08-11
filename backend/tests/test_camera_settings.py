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
        "preferences": {},
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


def test_per_camera_preferences_round_trip(tmp_data_root: Path):
    """Per-camera preferences persist and a single PUT covers all rows.

    The store contract is a top-level replace (the same one used by
    ``sensor_colors`` in the temperature module). The client keeps the
    full ``preferences`` map in memory and sends it on every PUT, so a
    single request with both rows is the realistic shape — and a fresh
    GET must surface everything the operator persisted.
    """
    app = _build_app(tmp_data_root)
    client = TestClient(app)

    resp = client.put(
        "/api/v1/modules/camera/settings",
        json={
            "preferences": {
                "/dev/video0": {
                    "custom_name": "Workshop ceiling",
                    "flip": True,
                    "mirror": False,
                    "hidden": False,
                },
                "/dev/video1": {
                    "custom_name": "Bench camera",
                    "flip": False,
                    "mirror": True,
                    "hidden": True,
                },
            }
        },
    )
    assert resp.status_code == 200
    merged = resp.json()
    assert set(merged["preferences"].keys()) == {"/dev/video0", "/dev/video1"}
    assert merged["preferences"]["/dev/video0"]["custom_name"] == "Workshop ceiling"
    assert merged["preferences"]["/dev/video0"]["flip"] is True
    assert merged["preferences"]["/dev/video1"]["hidden"] is True
    # MJPEG knobs were not in the payload — defaults survive.
    assert merged["jpeg_quality"] == 70
    assert merged["target_fps"] == 15

    # GET must surface the same payload.
    resp = client.get("/api/v1/modules/camera/settings")
    assert resp.status_code == 200
    persisted = resp.json()
    assert persisted["preferences"]["/dev/video0"]["custom_name"] == "Workshop ceiling"
    assert persisted["preferences"]["/dev/video1"]["hidden"] is True

    # On-disk file matches (so a fresh checkout keeps the operator's choices).
    on_disk = json.loads(
        (tmp_data_root / "modules" / "camera" / "settings.json").read_text(
            encoding="utf-8",
        )
    )
    assert set(on_disk["preferences"].keys()) == {"/dev/video0", "/dev/video1"}


def test_preferences_put_replaces_top_level_map(tmp_data_root: Path):
    """Documented store contract: a PUT replaces the ``preferences`` map.

    The settings store works by top-level ``dict.update``, so a
    second PUT that omits ``/dev/video0`` drops that row. The
    frontend pattern (read → modify → PUT the whole map in memory)
    is the canonical way to keep the union of rows.
    """
    app = _build_app(tmp_data_root)
    client = TestClient(app)

    # Seed both rows.
    client.put(
        "/api/v1/modules/camera/settings",
        json={
            "preferences": {
                "/dev/video0": {"custom_name": "first"},
                "/dev/video1": {"custom_name": "second"},
            }
        },
    )

    # Read-modify-write (the canonical frontend pattern): add a new
    # row to the existing map and PUT the union. /dev/video0 must
    # survive because the client re-sends it.
    persisted = client.get("/api/v1/modules/camera/settings").json()
    next_prefs = persisted["preferences"]
    next_prefs["/dev/video2"] = {"custom_name": "third", "hidden": True}
    resp = client.put(
        "/api/v1/modules/camera/settings",
        json={"preferences": next_prefs},
    )
    assert resp.status_code == 200
    merged = resp.json()
    assert set(merged["preferences"].keys()) == {
        "/dev/video0",
        "/dev/video1",
        "/dev/video2",
    }
    # Original entries untouched.
    assert merged["preferences"]["/dev/video0"]["custom_name"] == "first"
    assert merged["preferences"]["/dev/video1"]["custom_name"] == "second"
    assert merged["preferences"]["/dev/video2"]["hidden"] is True


def test_preferences_partial_row_persists_verbatim(tmp_data_root: Path):
    """Partial rows persist as the client wrote them; default-fill happens
    only inside the Pydantic ``CameraDevicePreference`` coercion path
    (``StreamManager.reload_config``).

    The frontend's ``coercePreference`` always produces rows with all
    four fields, so a partial PUT only happens during forward /
    backward-compat windows. The store's job is to keep the bytes
    durable; the consumer's job is to fill defaults where they are
    read. This test pins both halves: the round-trip preserves the
    shape the operator wrote, and the StreamManager falls back to
    defaults when a row is missing keys.
    """
    from modules.camera import router as camera_router
    from modules.camera.settings import CameraSettings

    app = _build_app(tmp_data_root)
    client = TestClient(app)

    resp = client.put(
        "/api/v1/modules/camera/settings",
        json={
            "preferences": {
                "/dev/video0": {"custom_name": "Renamed only"},
            }
        },
    )
    assert resp.status_code == 200
    # The round-trip preserves the partial shape — no implicit field
    # injection at the storage layer.
    assert resp.json()["preferences"]["/dev/video0"] == {"custom_name": "Renamed only"}

    # Where default-fill happens: the consumer coerces the persisted
    # payload into ``CameraSettings`` and gets a fully-populated row
    # for ``/dev/video0``, with ``flip``/``mirror``/``hidden``
    # materialised from the Pydantic schema.
    settings = SettingsStore(
        module_id="camera",
        data_root=tmp_data_root,
        defaults=CameraSettings(),
    )
    camera_router.bind_settings_store(settings)
    cfg = camera_router._stream_manager.reload_config()
    assert "/dev/video0" in cfg.preferences
    assert cfg.preferences["/dev/video0"].custom_name == "Renamed only"
    assert cfg.preferences["/dev/video0"].flip is False
    assert cfg.preferences["/dev/video0"].mirror is False
    assert cfg.preferences["/dev/video0"].hidden is False


def test_preferences_invalid_payload_is_dropped_at_consumer(tmp_data_root: Path):
    """A non-dict ``preferences`` payload is stored verbatim by the router,
    then filtered to defaults when the StreamManager coerces the dict
    into ``CameraSettings``.

    Per the settings-module contract (§ 6), the settings store itself is
    intentionally untyped; validation is the module's job, and it lives
    in :meth:`StreamManager.reload_config`. A non-dict map ends up
    coerced by Pydantic into the empty default, which is the documented
    safe behaviour: a malformed payload cannot crash the streaming
    loop.
    """
    from modules.camera import router as camera_router
    from modules.camera.settings import CameraSettings

    settings = SettingsStore(
        module_id="camera",
        data_root=tmp_data_root,
        defaults=CameraSettings(),
    )
    camera_router.bind_settings_store(settings)
    manager = camera_router._stream_manager

    # This PUT succeeds at the router (the store accepts any JSON
    # object), but the manager drops it back to defaults because
    # Pydantic cannot coerce a string into the ``preferences`` field.
    settings.write_all({"preferences": "not-a-dict"})
    cfg = manager.reload_config()
    assert cfg.preferences == {}

    # A row of the wrong type is dropped by the per-row validator.
    settings.write_all({"preferences": {"/dev/video0": "not-a-row"}})
    cfg = manager.reload_config()
    assert cfg.preferences == {}