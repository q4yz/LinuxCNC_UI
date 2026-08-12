"""Tests for the base-thread snapshot endpoint.

The snapshot endpoint (``GET /api/v1/base-thread/snapshot``) is
the dashboard's "base thread" — a single 1 Hz round-trip that
bundles every slow stream (program progress, temperature sensors,
tool list) into one payload so the browser only pays one HTTP
request per second regardless of how many panels are mounted.

These tests pin the contract the dashboard depends on:

* the response shape mirrors ``BaseThreadSnapshotResponse``,
* offline (``get_machine_stat() is None``) returns the safe
  zeroed payload without raising,
* the line-count cache populates ``progress.total_lines``,
* ``current_line`` advances while the interpreter is reading,
* sensors / tools mirror the individual endpoint shapes,
* after ``unload`` the progress block reverts to zeros.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------- #
# Helpers                                                                 #
# ---------------------------------------------------------------------- #


def _reset_mock_program_state() -> None:
    """Reset the mock's program lifecycle fields to the "no program" baseline."""
    from hardware import linuxcnc_mock

    with linuxcnc_mock._machine_state.lock:
        linuxcnc_mock._machine_state.file = ""
        linuxcnc_mock._machine_state.current_line = 0
        linuxcnc_mock._machine_state.total_lines = 0
        linuxcnc_mock._machine_state.interp_state = linuxcnc_mock.INTERP_IDLE


def _reset_line_count_cache() -> None:
    """Drop the line-count cache so each test starts from a clean slate."""
    from services.line_count_cache import unregister_all

    unregister_all()


def _isolated_program_root(
    tmp_path: Path, monkeypatch, filename: str = "test.gcode"
) -> Path:
    """Point the program service at ``tmp_path`` and seed a gcode file."""
    from services import domain_file_services, reset_service_cache

    monkeypatch.setattr(
        domain_file_services, "_NC_FILES_DIR", tmp_path, raising=False
    )
    reset_service_cache()

    target = tmp_path / filename
    target.write_text("G28\nG1 X0 Y0 F1500\nM30\n", encoding="utf-8")
    return target


def _base_thread_app(tmp_data_root) -> tuple[FastAPI, object]:
    """Build a minimal FastAPI app that mounts every module the
    snapshot endpoint depends on.

    The snapshot endpoint touches the program, temperature, and
    tools modules so we boot all three via the registry's
    ``boot(app)`` call. ``tmp_data_root`` becomes the active
    data root for module services (settings, programs, etc.).

    The flat ``base_thread`` router lives outside the module
    registry, so we ``include_router`` it explicitly — mirroring
    what ``backend/main.py`` does at boot.
    """
    from core.event_bus import EventBus
    from core.module_registry import ModuleRegistry
    from routers import base_thread as base_thread_router

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    candidates = []
    for module_name in ("program", "temperature", "tools"):
        candidates.append(_import_setup(module_name))
    reg.boot(app, bus=EventBus(), candidates=candidates)
    app.include_router(base_thread_router.router)
    return app, reg


def _import_setup(module_name: str):
    """Import a module's ``setup()`` factory by name."""
    import importlib

    module = importlib.import_module(f"modules.{module_name}.module")
    return module.setup()


# ---------------------------------------------------------------------- #
# Offline / safety                                                        #
# ---------------------------------------------------------------------- #


def test_snapshot_returns_safe_zeroed_payload_when_offline(
    tmp_data_root, clean_env, monkeypatch
):
    """When the NML status channel is offline the endpoint must
    return a 200 with the safe-zeroed payload — not raise.

    The dashboard's empty-state UI handles the no-data case, but
    only when the response body parses successfully. A 5xx would
    blank the widget.
    """
    _reset_mock_program_state()
    _reset_line_count_cache()

    from routers import base_thread as bt
    from services.line_count_cache import unregister_all

    monkeypatch.setattr(bt, "get_machine_stat", lambda: None)

    app, _ = _base_thread_app(tmp_data_root)
    client = TestClient(app)
    resp = client.get("/api/v1/base-thread/snapshot")
    assert resp.status_code == 200

    body = resp.json()
    assert body["progress"] == {
        "current_line": 0,
        "motion_line": 0,
        "total_lines": 0,
        "file": "",
        "interp_state": 1,  # INTERP_IDLE
    }
    assert body["sensors"] == {}
    assert body["tools"] == []
    assert "timestamp" in body
    unregister_all()


# ---------------------------------------------------------------------- #
# End-to-end through the registry                                         #
# ---------------------------------------------------------------------- #


def test_snapshot_mirrors_individual_endpoints(
    tmp_data_root, clean_env, monkeypatch, tmp_path
):
    """End-to-end: load a file, run, and assert the snapshot
    surfaces ``progress.total_lines`` from the cache, ``current_line``
    advancing, the live sensor reading, and the (empty) tool list.
    """
    _reset_mock_program_state()
    _reset_line_count_cache()
    _isolated_program_root(tmp_data_root, monkeypatch)

    # The tools loader reads the active ``hardware.json`` on import.
    # Patch it to a directory with no tools so the test sees a clean
    # baseline (the dev environment's real ``hardware.json`` is
    # ignored). The mock's sensor list is reseeded against the same
    # empty path so the only sensor is the one we inject below.
    from services import tools_loader

    empty = tmp_path / "empty_active"
    empty.mkdir()
    monkeypatch.setattr(tools_loader, "_PROJECT_ROOT", empty)
    monkeypatch.setattr("hardware.linuxcnc_mock._PROJECT_ROOT", empty)
    from hardware import linuxcnc_mock

    linuxcnc_mock.reseed_from_hardware_json()

    app, _ = _base_thread_app(tmp_data_root)
    client = TestClient(app)

    # Inject the sensor reading we want to assert on. The mock
    # re-seeded the dict empty above, so the only key is ours.
    with linuxcnc_mock._machine_state.lock:
        linuxcnc_mock._machine_state.temperatures["extruder"] = {
            "actual": 195.4,
            "target": 200.0,
        }

    # Load the program via the public router so the cache is
    # populated.
    assert client.post(
        "/api/v1/modules/program/load",
        json={"filename": "test.gcode"},
    ).status_code == 200
    assert client.post("/api/v1/modules/program/run").status_code == 200

    time.sleep(0.35)

    resp = client.get("/api/v1/base-thread/snapshot")
    assert resp.status_code == 200
    body = resp.json()

    # Progress block — total_lines comes from the cache, current
    # line advanced while the interpreter was reading.
    assert body["progress"]["total_lines"] == 3
    assert body["progress"]["current_line"] > 0
    assert body["progress"]["interp_state"] == 2  # INTERP_READING
    assert body["progress"]["file"].endswith("test.gcode")

    # Sensors block — the snapshot is now the canonical surface for
    # the sensor dict (the legacy ``GET /sensors`` endpoint was
    # removed in favour of this snapshot). Assert the inline shape
    # directly so a regression that breaks either the snapshot or
    # the underlying ``_collect_sensors`` helper surfaces here.
    assert body["sensors"]["extruder"]["actual"] == pytest.approx(195.4)
    assert body["sensors"]["extruder"]["target"] == pytest.approx(200.0)

    # Tools block — the snapshot is now the canonical surface for
    # the tool list. Empty because the test root has no
    # ``hardware.json``, but the field must be present and
    # serialise as a JSON array.
    assert isinstance(body["tools"], list)
    assert body["tools"] == []

    assert "timestamp" in body


def test_snapshot_progress_zeros_after_unload(
    tmp_data_root, clean_env, monkeypatch
):
    """After ``POST /unload`` the progress block must drop back to
    zeros; a stale ``total_lines`` would leave the dashboard bar
    stuck at the previous value.
    """
    _reset_mock_program_state()
    _reset_line_count_cache()
    _isolated_program_root(tmp_data_root, monkeypatch)

    app, _ = _base_thread_app(tmp_data_root)
    client = TestClient(app)
    assert client.post(
        "/api/v1/modules/program/load",
        json={"filename": "test.gcode"},
    ).status_code == 200

    loaded = client.get("/api/v1/base-thread/snapshot").json()
    assert loaded["progress"]["total_lines"] == 3
    assert loaded["progress"]["file"].endswith("test.gcode")

    assert client.post("/api/v1/modules/program/unload").status_code == 200

    cleared = client.get("/api/v1/base-thread/snapshot").json()
    assert cleared["progress"] == {
        "current_line": 0,
        "motion_line": 0,
        "total_lines": 0,
        "file": "",
        "interp_state": 1,  # INTERP_IDLE
    }


def test_snapshot_timestamp_is_iso8601_utc(
    tmp_data_root, clean_env, monkeypatch
):
    """The snapshot's ``timestamp`` must be an ISO-8601 UTC string
    ending in ``Z`` so the frontend can use it to detect a stalled
    poll without parsing locale-dependent formats.
    """
    _reset_mock_program_state()
    _reset_line_count_cache()

    app, _ = _base_thread_app(tmp_data_root)
    client = TestClient(app)
    body = client.get("/api/v1/base-thread/snapshot").json()
    ts = body["timestamp"]
    # Format: ``2026-08-12T12:34:56.789012Z``
    assert ts.endswith("Z")
    assert "T" in ts


# ---------------------------------------------------------------------- #
# Tool telemetry overlay                                                   #
# ---------------------------------------------------------------------- #


def _write_v2_hardware_json(tmp_path: Path, payload: dict) -> Path:
    """Drop a v2-shape ``hardware.json`` into ``tmp_path`` and
    return the directory the loader reads from."""
    import json

    target = tmp_path / "machine_config" / "active"
    target.mkdir(parents=True, exist_ok=True)
    (target / "hardware.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return tmp_path


def test_snapshot_overlays_spindle_digital_runtime_state(
    tmp_data_root, clean_env, monkeypatch, tmp_path
):
    """The snapshot's ``tools`` block must overlay every operator-
    facing spindle telemetry field from the mock's
    ``spindle_actual`` dict: ``actual_rpm``, ``is_connected``,
    ``error_count``. The ToolPanel's spindle card reads all three
    — a regression that drops any of them shows up as a blank
    tile on the dashboard.
    """
    _reset_mock_program_state()
    _reset_line_count_cache()
    _isolated_program_root(tmp_data_root, monkeypatch)

    from hardware import linuxcnc_mock
    from services import tools_loader

    # Drop a hardware.json with a single spindle_digital tool so
    # the snapshot surfaces exactly one row. Re-point both the
    # mock's seeder AND the tools loader at ``tmp_path`` so the
    # fixture is honoured.
    active_root = _write_v2_hardware_json(tmp_path, {
        "version": "2.0",
        "machine": "test",
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": "cartesian",
        "hal_type": "remora",
        "axes": [],
        "steppers": [],
        "drivers": [],
        "endstops": [],
        "tools": [
            {
                "id": "spindle_digital",
                "type": "spindle_digital",
                "min_rpm": 5000,
                "max_rpm": 24000,
            },
        ],
        "temperature_sensors": [],
        "fans": [],
    })
    monkeypatch.setattr(tools_loader, "_PROJECT_ROOT", active_root)
    monkeypatch.setattr("hardware.linuxcnc_mock._PROJECT_ROOT", active_root)
    linuxcnc_mock.reseed_from_hardware_json()

    # Inject non-default telemetry so the assertion proves the
    # read-through path, not the default-zero fallback.
    with linuxcnc_mock._machine_state.lock:
        linuxcnc_mock._machine_state.spindle_actual["spindle_digital"] = {
            "actual": 11800,
            "is_connected": True,
            "error_count": 3,
        }

    app, _ = _base_thread_app(tmp_data_root)
    client = TestClient(app)
    body = client.get("/api/v1/base-thread/snapshot").json()

    assert len(body["tools"]) == 1
    tool = body["tools"][0]
    assert tool["id"] == "spindle_digital"
    assert tool["actual_rpm"] == 11800
    assert tool["is_connected"] is True
    assert tool["error_count"] == 3
    # Static fields pass through unchanged.
    assert tool["min_rpm"] == 5000
    assert tool["max_rpm"] == 24000
