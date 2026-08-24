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
from tests._module_app_factory import build_module_app

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus


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
    from hardware.mock.test_helpers.mock_helpers import reset_program_state
    reset_program_state()


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


def _program_app(tmp_data_root, clean_env=None):
    """Build a FastAPI app with the program module wired up."""
    return build_module_app("program", tmp_data_root), None



def _state_snapshot() -> dict:
    """Read the mock's program lifecycle fields under the lock."""
    from hardware import connection

    stat = connection.get_machine_stat()
    if stat is not None:
        poll = getattr(stat, "poll", None)
        if callable(poll):
            poll()
        return {
            "file": stat.file,
            "current_line": stat.current_line,
            "total_lines": stat.total_lines,
            "interp_state": stat.interp_state,
        }
    return {
        "file": "",
        "current_line": 0,
        "total_lines": 0,
        "interp_state": 0,
    }


# ---------------------------------------------------------------------- #
# Load                                                                    #
# ---------------------------------------------------------------------- #



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



def test_program_router_exposes_short_operation_ids(tmp_data_root, clean_env):
    """Each lifecycle endpoint must expose a short ``operationId``.

    The OpenAPI generator turns ``operationId`` into the generated
    client's static method name. Without an explicit ``operationId``
    the generator falls back to a URL-derived long name
    (``loadProgramApiV1ModulesProgramLoadPost``), and the frontend's
    calls to ``ModulesProgramService.loadProgram(...)`` etc. fail
    with ``TypeError: ... is not a function``.

    The fix is six one-line ``operation_id=`` arguments on the
    router decorators. This test pins the contract — a future
    contributor who drops an ``operation_id=`` will trip the test
    instead of breaking the dashboard silently.
    """
    app, _ = _program_app(tmp_data_root)
    schema = app.openapi()
    paths = schema["paths"]
    expected = {
        ("/api/v1/modules/program/load", "post"): "loadProgram",
        ("/api/v1/modules/program/run", "post"): "runProgram",
        ("/api/v1/modules/program/stop", "post"): "stopProgram",
        ("/api/v1/modules/program/unload", "post"): "unloadProgram",
        ("/api/v1/modules/program/pause", "post"): "pauseProgram",
        ("/api/v1/modules/program/resume", "post"): "resumeProgram",
    }
    for (path, method), op_id in expected.items():
        assert path in paths, f"endpoint {path!r} missing from OpenAPI schema"
        assert method in paths[path], (
            f"endpoint {method.upper()} {path!r} missing from OpenAPI schema"
        )
        actual = paths[path][method].get("operationId")
        assert actual == op_id, (
            f"{method.upper()} {path!r}: expected operationId={op_id!r}, "
            f"got {actual!r}. The frontend will call "
            f"ModulesProgramService.{op_id}(...) — without this "
            f"operationId the generated method name does not match "
            f"and the dashboard shows 'is not a function'."
        )
