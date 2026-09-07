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

import importlib
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import hardware.Connection as connection_mod
from hardware.mock.test_helpers.mock_helpers import (
    reset_program_state,
    reseed_from_hardware_json,
    seed_spindle_actual,
    seed_temperature,
)


# ---------------------------------------------------------------------- #
# Helpers                                                                 #
# ---------------------------------------------------------------------- #


def _reset_mock_program_state() -> None:
    """Reset the mock's program lifecycle fields to the "no program" baseline."""
    reset_program_state()


def _reset_line_count_cache() -> None:
    """Drop the line-count cache so each test starts from a clean slate."""
    from services.line_count_cache import unregister_all

    unregister_all()


def _point_hardware_config_at(monkeypatch, tmp_path) -> None:
    """Point :class:`HardwareConfigService` at ``tmp_path``.

    Replaces the historical
    ``monkeypatch.setattr(config_mapper, "_PROJECT_ROOT", tmp_path)``
    seam — the tools module's loader no longer exposes a module-
    level ``_PROJECT_ROOT``; the seam is the
    :class:`HardwareConfigService` constructor's ``repo_root`` arg.
    """
    from services.HardwareConfigService import HardwareConfigService

    original_init = HardwareConfigService.__init__

    def _init(self, active_path=None, repo_root=None):
        return original_init(
            self,
            active_path=active_path,
            repo_root=repo_root if repo_root is not None else tmp_path,
        )

    monkeypatch.setattr(HardwareConfigService, "__init__", _init)


def _isolated_program_root(
    tmp_path: Path, monkeypatch, filename: str = "test.gcode"
) -> Path:
    """Point the program service at ``tmp_path`` and seed a gcode file."""
    from services import domain_file_services, reset_service_cache

    monkeypatch.setattr(
        domain_file_services.paths, "NC_FILES_DIR", tmp_path
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
    from routers import BaseThreadRouter as base_thread_router

    app = FastAPI()
    for module_name in ("program", "temperature", "tools"):
        app.include_router(
            importlib.import_module(f"routers.{module_name}").router
        )
    app.include_router(base_thread_router.router)
    return app, None


def _import_setup(module_name: str):
    """Import a module's ``setup()`` factory by name."""
    import importlib

    module = importlib.import_module(f"modules.{module_name}.module")
    return module.setup()


# ---------------------------------------------------------------------- #
# Offline / safety                                                        #
# ---------------------------------------------------------------------- #





def test_snapshot_timestamp_is_iso8601_utc(
    tmp_data_root, clean_env, monkeypatch, tmp_path
):
    """The snapshot's ``timestamp`` must be an ISO-8601 UTC string
    ending in ``Z`` so the frontend can use it to detect a stalled
    poll without parsing locale-dependent formats.
    """
    _point_hardware_config_at(monkeypatch, tmp_path)
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


def _bare_base_thread_app(tmp_data_root) -> FastAPI:
    """Minimal helper used by the snapshot-mode tests below.

    Mirrors :func:`_base_thread_app` minus the ``program`` /
    ``temperature`` / ``tools`` module boot — those tests only assert
    on the *presence* of fields, not their contents, so the flat
    ``base_thread`` router alone is enough.
    """
    from routers import BaseThreadRouter

    app = FastAPI()
    app.include_router(BaseThreadRouter.router)
    return app


def test_snapshot_default_mode_returns_all_fields(
    tmp_data_root, clean_env, monkeypatch, tmp_path
):
    """Omitting ``?mode=`` (legacy default) returns every field —
    backward compatibility for the dashboard's existing 1 Hz poll.
    """
    _point_hardware_config_at(monkeypatch, tmp_path)
    _reset_mock_program_state()
    _reset_line_count_cache()

    app = _bare_base_thread_app(tmp_data_root)
    client = TestClient(app)

    body = client.get("/api/v1/base-thread/snapshot").json()
    assert set(body.keys()) == {
        "progress",
        "sensors",
        "tools",
        "timestamp",
        "axis",
    }


def test_snapshot_mode_all_equivalent_to_default(
    tmp_data_root, clean_env, monkeypatch, tmp_path
):
    """``?mode=all`` must produce the same key set as the legacy
    default — the explicit form for callers that want to advertise
    they want the full payload.
    """
    _point_hardware_config_at(monkeypatch, tmp_path)
    _reset_mock_program_state()
    _reset_line_count_cache()

    app = _bare_base_thread_app(tmp_data_root)
    client = TestClient(app)

    body = client.get("/api/v1/base-thread/snapshot?mode=all").json()
    assert set(body.keys()) == {
        "progress",
        "sensors",
        "tools",
        "timestamp",
        "axis",
    }






def test_snapshot_mode_invalid_value_returns_422(
    tmp_data_root, clean_env, monkeypatch
):
    """Unknown mode values must be rejected with ``422 Unprocessable
    Entity`` so callers catch typos early instead of silently
    receiving an empty payload.
    """
    _reset_mock_program_state()
    _reset_line_count_cache()

    app = _bare_base_thread_app(tmp_data_root)
    client = TestClient(app)

    resp = client.get("/api/v1/base-thread/snapshot?mode=garbage")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "garbage" in detail
    # Valid values are echoed in the error so the caller knows what
    # they could have asked for.
    assert "static" in detail
    assert "base" in detail



