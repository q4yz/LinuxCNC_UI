"""Tests for the program module's lifecycle HTTP surface.

The program module mirrors LinuxCNC's documented two-step "load
then start" lifecycle:

1. ``POST /load`` -> ``command.program_open(path)`` (sets
   ``stat.file`` while ``interp_state`` stays ``INTERP_IDLE``).
2. ``POST /run``  -> ``auto(AUTO_RUN, line)`` (flips
   ``interp_state`` to ``INTERP_READING``). The endpoint refuses
   with ``409 Conflict`` when no file has been loaded.

These tests cover the state machine end-to-end through the FastAPI
router, including the WebSocket telemetry payload that the
dashboard widget subscribes to.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.module_registry import ModuleRegistry


# ---------------------------------------------------------------------- #
# Helpers                                                                 #
# ---------------------------------------------------------------------- #


def _reset_mock_program_state() -> None:
    """Reset the mock's program lifecycle fields to the "no program" baseline.

    The mock's ``_machine_state`` is a module-level singleton that
    other tests in the same session may have touched. Each test
    starts from a clean slate so the lifecycle assertions are
    deterministic.
    """
    from hardware import linuxcnc_mock

    with linuxcnc_mock._machine_state.lock:
        linuxcnc_mock._machine_state.file = ""
        linuxcnc_mock._machine_state.current_line = 0
        linuxcnc_mock._machine_state.total_lines = 0
        linuxcnc_mock._machine_state.interp_state = (
            linuxcnc_mock.INTERP_IDLE
        )


def _isolated_program_root(
    tmp_path: Path, monkeypatch, filename: str = "test.gcode"
) -> Path:
    """Point the program service at ``tmp_path`` and seed a gcode file.

    Returns the absolute path of the seeded file.
    """
    from services import domain_file_services, reset_service_cache

    monkeypatch.setattr(
        domain_file_services, "_NC_FILES_DIR", tmp_path, raising=False
    )
    reset_service_cache()

    target = tmp_path / filename
    target.write_text("G28\nG1 X0 Y0 F1500\nM30\n", encoding="utf-8")
    return target


def _program_app(tmp_data_root) -> tuple[FastAPI, ModuleRegistry]:
    """Build a fresh FastAPI app + registry with the program module loaded."""
    from modules.program.module import setup

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, bus=EventBus(), candidates=[setup()])
    return app, reg


def _state_snapshot() -> dict:
    """Read the mock's program lifecycle fields under the lock."""
    from hardware import linuxcnc_mock

    with linuxcnc_mock._machine_state.lock:
        return {
            "file": linuxcnc_mock._machine_state.file,
            "current_line": linuxcnc_mock._machine_state.current_line,
            "total_lines": linuxcnc_mock._machine_state.total_lines,
            "interp_state": linuxcnc_mock._machine_state.interp_state,
        }


# ---------------------------------------------------------------------- #
# Load                                                                    #
# ---------------------------------------------------------------------- #


def test_load_sets_file_and_resets_to_interp_idle(
    tmp_data_root, clean_env, monkeypatch
):
    """``POST /load`` forwards ``program_open`` to the mock.

    The mock's ``program_open`` sets ``stat.file`` to the absolute
    path on disk, resets ``current_line`` to 0, and stamps
    ``total_lines`` to its 1000-line placeholder. The interpreter
    must stay in ``INTERP_IDLE`` so the widget renders the "Loaded"
    branch rather than the "Running" branch.
    """
    _reset_mock_program_state()
    target = _isolated_program_root(tmp_data_root, monkeypatch)

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/program/load",
        json={"filename": "test.gcode"},
    )
    assert resp.status_code == 200

    snap = _state_snapshot()
    assert snap["file"] == str(target)
    assert snap["current_line"] == 0
    assert snap["total_lines"] == 1000
    assert snap["interp_state"] == 1  # INTERP_IDLE


def test_load_returns_404_when_file_missing(
    tmp_data_root, clean_env, monkeypatch
):
    """``POST /load`` returns 404 when the filename is unknown."""
    _reset_mock_program_state()
    _isolated_program_root(tmp_data_root, monkeypatch)

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/program/load",
        json={"filename": "nope.gcode"},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_load_rejects_path_traversal(
    tmp_data_root, clean_env, monkeypatch
):
    """``POST /load`` refuses filenames that escape ``safe_join``."""
    _reset_mock_program_state()
    _isolated_program_root(tmp_data_root, monkeypatch)

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/program/load",
        json={"filename": "../etc/passwd"},
    )
    assert resp.status_code == 400
    assert "escapes" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------- #
# Run                                                                     #
# ---------------------------------------------------------------------- #


def test_run_returns_409_when_no_file_loaded(tmp_data_root, clean_env):
    """``POST /run`` refuses to start the interpreter on an empty file.

    This is the "strict" mode contract the frontend relies on to
    surface a clear "no program loaded" message instead of the
    interpreter silently reading nothing.
    """
    _reset_mock_program_state()

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    resp = client.post("/api/v1/modules/program/run")
    assert resp.status_code == 409
    assert "load" in resp.json()["detail"].lower()


def test_run_after_load_advances_current_line(
    tmp_data_root, clean_env, monkeypatch
):
    """End-to-end: load then run, then assert ``current_line > 0``.

    The mock's simulation loop ticks every 100 ms; we wait 350 ms
    to give the background thread room to advance the line counter
    at least twice.
    """
    _reset_mock_program_state()
    _isolated_program_root(tmp_data_root, monkeypatch)

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    assert client.post(
        "/api/v1/modules/program/load",
        json={"filename": "test.gcode"},
    ).status_code == 200
    assert client.post("/api/v1/modules/program/run").status_code == 200

    time.sleep(0.35)

    snap = _state_snapshot()
    assert snap["current_line"] > 0
    assert snap["interp_state"] == 2  # INTERP_READING


def test_stop_after_run_resets_state(
    tmp_data_root, clean_env, monkeypatch
):
    """``POST /stop`` aborts the run and returns the interpreter to idle."""
    _reset_mock_program_state()
    _isolated_program_root(tmp_data_root, monkeypatch)

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    client.post(
        "/api/v1/modules/program/load",
        json={"filename": "test.gcode"},
    )
    client.post("/api/v1/modules/program/run")
    time.sleep(0.2)
    stop = client.post("/api/v1/modules/program/stop")
    assert stop.status_code == 200

    snap = _state_snapshot()
    assert snap["interp_state"] == 1  # INTERP_IDLE
    assert snap["current_line"] == 0


def test_pause_then_resume_keeps_loaded_file(
    tmp_data_root, clean_env, monkeypatch
):
    """Pause/resume must not clear the loaded file.

    The two-step lifecycle is preserved through pause/resume: the
    file pointer stays set so a subsequent ``POST /run`` (or the
    implicit ``auto(AUTO_RESUME)`` behind it) can keep going.
    """
    _reset_mock_program_state()
    target = _isolated_program_root(tmp_data_root, monkeypatch)

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    client.post(
        "/api/v1/modules/program/load",
        json={"filename": "test.gcode"},
    )
    client.post("/api/v1/modules/program/run")
    time.sleep(0.2)
    assert client.post("/api/v1/modules/program/pause").status_code == 200
    assert client.post("/api/v1/modules/program/resume").status_code == 200

    snap = _state_snapshot()
    assert snap["file"] == str(target)


# ---------------------------------------------------------------------- #
# WebSocket telemetry                                                     #
# ---------------------------------------------------------------------- #


def test_websocket_payload_broadcasts_total_lines(
    tmp_data_root, clean_env, monkeypatch
):
    """The telemetry loop broadcasts ``total_lines`` alongside ``current_line``.

    Before this fix the frontend's ``printProgress`` getter always
    returned 0 because ``total_lines`` was never wire-serialized;
    loading a file must surface the mock's 1000-line placeholder
    on the next tick so the progress bar can finally move.
    """
    _reset_mock_program_state()
    _isolated_program_root(tmp_data_root, monkeypatch)

    from routers.websocket import get_current_state

    # ``get_current_state`` is the synchronous builder the
    # telemetry loop serialises every tick. Pre-load the snapshot
    # and confirm ``total_lines`` is 0 (no file loaded yet).
    before = get_current_state()
    assert before["total_lines"] == 0

    # Drive a load through the public router.
    app, _ = _program_app(tmp_data_root)
    TestClient(app).post(
        "/api/v1/modules/program/load",
        json={"filename": "test.gcode"},
    )

    after = get_current_state()
    assert after["total_lines"] == 1000
    assert after["file"].endswith("test.gcode")
    assert after["interp_state"] == 1  # INTERP_IDLE
