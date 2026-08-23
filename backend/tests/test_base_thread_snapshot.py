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


def test_snapshot_returns_safe_zeroed_payload_when_offline(
    tmp_data_root, clean_env, monkeypatch, tmp_path
):
    """When the NML status channel is offline the endpoint must
    return a 200 with the safe-zeroed payload — not raise.

    The dashboard's empty-state UI handles the no-data case, but
    only when the response body parses successfully. A 5xx would
    blank the widget.

    The test points the hardware config at an empty directory so
    the active ``hardware.json`` declared by the dev environment
    (the real ``machine_config/active/hardware.json``) does not
    leak into the offline payload — the contract the test pins is
    the *offline* surface, not the operator's real machine.
    """
    _reset_mock_program_state()
    _reset_line_count_cache()

    from services.line_count_cache import unregister_all

    empty = tmp_path / "empty_active"
    empty.mkdir()
    _point_hardware_config_at(monkeypatch, empty)
    reseed_from_hardware_json(empty)

    monkeypatch.setattr(
        connection_mod, "get_machine_stat", lambda *a, **k: None
    )

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
    # ``tools`` is loaded from ``hardware.json`` independently of
    # the NML stat channel — the operator-facing panel still wants
    # to show the configured tool list even when LinuxCNC is offline.
    # We assert the field is a dict (per ``BaseThreadSnapshotResponse.tools``);
    # the contents depend on the dev environment's ``hardware.json``.
    assert isinstance(body.get("tools", {}), dict)
    assert body.get("tools", {}) == {}
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
        "tools": [],
        # Defined as a standalone sensor
        "temperature_sensors": [
            {"id": "extruder"},
        ],
        "fans": [],
    })
    _point_hardware_config_at(monkeypatch, active_root)

    # 2. Reseed the unified mock
    reseed_from_hardware_json(active_root)

    app, _ = _base_thread_app(tmp_data_root)
    client = TestClient(app)

    # 3. Seed the temperature in the unified mock.
    # (We can drop 'target' here since standalone sensors don't use it)
    # 3. Seed the temperature in the unified mock.
    # (Pass a dummy target=0.0 to satisfy the Python function signature.
    # The new DDD factory will safely strip it from the final JSON.)
    seed_temperature("extruder", actual=195.4, target=0.0)

    assert client.post(
        "/api/v1/modules/program/load",
        json={"filename": "test.gcode"},
    ).status_code == 200
    assert client.post("/api/v1/modules/program/run").status_code == 200

    time.sleep(0.35)

    resp = client.get("/api/v1/base-thread/snapshot")
    assert resp.status_code == 200
    body = resp.json()

    assert body["progress"]["total_lines"] == 3
    assert body["progress"]["current_line"] > 0
    assert body["progress"]["interp_state"] == 2  # INTERP_READING
    assert body["progress"]["file"].endswith("test.gcode")

    # 4. Assert only on the fields the Domain Model allows for a standalone sensor
    assert body["sensors"]["extruder"]["actual"] == pytest.approx(195.4)
    # The 'target' assertion is DELETED because standalone sensors do not have targets.
    assert body["sensors"]["extruder"]["tool_id"] == "extruder"

    assert isinstance(body.get("tools", {}), dict)
    assert body.get("tools", {}) == {}

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
    _point_hardware_config_at(monkeypatch, active_root)
    reseed_from_hardware_json(active_root)

    # Inject non-default telemetry so the assertion proves the
    # read-through path, not the default-zero fallback.
    seed_spindle_actual(
        "spindle_digital",
        actual=11800,
        is_connected=True,
        error_count=3,
    )

    app, _ = _base_thread_app(tmp_data_root)
    client = TestClient(app)
    body = client.get("/api/v1/base-thread/snapshot").json()

    assert len(body["tools"]) == 1
    tool = body["tools"]["spindle_digital"]
    assert tool["id"] == "spindle_digital"
    assert tool["actual_rpm"] == 11800
    assert tool["is_connected"] is True
    assert tool["error_count"] == 3
    # Static fields pass through unchanged.
    assert tool["min_rpm"] == 5000
    assert tool["max_rpm"] == 24000


# ---------------------------------------------------------------------- #
# ``?mode=`` field-masking                                                #
# ---------------------------------------------------------------------- #
#
# These tests pin the contract introduced by the ``include_if`` /
# ``response_model_exclude_none=True`` combination on the
# ``GET /api/v1/base-thread/snapshot`` endpoint.
#
# The tests deliberately avoid the broken ``hardware.mock.linuxcnc_mock``
# / ``hardware.mock.mock_system`` monkeypatch seams that some of the
# legacy tests use — they only verify which keys are present in the
# response body, which is the entire surface area of the new feature.


def _bare_base_thread_app(tmp_data_root) -> FastAPI:
    """Build the minimal app + router for ``?mode=`` tests.

    Mirrors :func:`_base_thread_app` minus the ``program`` /
    ``temperature`` / ``tools`` module boot — those modules trigger
    broken mock-helper paths on the current tree. We only need the
    ``base_thread`` flat router for these tests, since they assert on
    the *presence* of fields, not their contents.
    """
    from routers import BaseThreadRouter as base_thread_router

    app = FastAPI()
    app.include_router(base_thread_router.router)
    return app


def test_snapshot_default_mode_returns_all_fields(
    tmp_data_root, clean_env, monkeypatch
):
    """Omitting ``?mode=`` (legacy default) returns every field —
    backward compatibility for the dashboard's existing 1 Hz poll.
    """
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
    tmp_data_root, clean_env, monkeypatch
):
    """``?mode=all`` must produce the same key set as the legacy
    default — the explicit form for callers that want to advertise
    they want the full payload.
    """
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


def test_snapshot_mode_static_returns_only_axis_and_timestamp(
    tmp_data_root, clean_env, monkeypatch
):
    """``?mode=static`` returns only the cached axis config plus the
    snapshot's own ``timestamp``. The dynamic sub-snapshots
    (``progress``, ``sensors``, ``tools``) must be absent.
    """
    _reset_mock_program_state()
    _reset_line_count_cache()

    app = _bare_base_thread_app(tmp_data_root)
    client = TestClient(app)

    body = client.get("/api/v1/base-thread/snapshot?mode=static").json()
    assert set(body.keys()) == {"axis", "timestamp"}
    assert isinstance(body["axis"], dict)


def test_snapshot_mode_base_returns_only_dynamic_subs(
    tmp_data_root, clean_env, monkeypatch
):
    """``?mode=base`` returns ``progress``, ``sensors``, ``tools``,
    and ``timestamp``. ``axis`` (cached static config) must be
    absent — the 1 Hz poll shouldn't pay for it every second.
    """
    _reset_mock_program_state()
    _reset_line_count_cache()

    app = _bare_base_thread_app(tmp_data_root)
    client = TestClient(app)

    body = client.get("/api/v1/base-thread/snapshot?mode=base").json()
    assert set(body.keys()) == {"progress", "sensors", "tools", "timestamp"}
    assert "axis" not in body


def test_snapshot_mode_progress_returns_only_progress(
    tmp_data_root, clean_env, monkeypatch
):
    """``?mode=progress`` isolates a single sub-snapshot so a panel
    that only watches ``current_line`` doesn't pay for sensors/tools.
    """
    _reset_mock_program_state()
    _reset_line_count_cache()

    app = _bare_base_thread_app(tmp_data_root)
    client = TestClient(app)

    body = client.get("/api/v1/base-thread/snapshot?mode=progress").json()
    assert set(body.keys()) == {"progress", "timestamp"}
    assert "sensors" not in body
    assert "tools" not in body
    assert "axis" not in body


def test_snapshot_mode_combined_static_base_returns_all(
    tmp_data_root, clean_env, monkeypatch
):
    """``?mode=static,base`` composes the two tiers — equivalent
    to ``?mode=all`` for the dashboard's full payload.
    """
    _reset_mock_program_state()
    _reset_line_count_cache()

    app = _bare_base_thread_app(tmp_data_root)
    client = TestClient(app)

    body = client.get(
        "/api/v1/base-thread/snapshot?mode=static,base"
    ).json()
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


def test_include_if_helper_returns_value_when_mode_matches():
    """Unit test for :func:`core.field_masking.include_if`.

    The mapper only uses straight conditionals today (the per-field
    rule is clearer inline), but the helper is exposed for other
    modules that want the same DRY guarantee. Pin its behaviour so
    future refactors can't silently change semantics.
    """
    from core.field_masking import include_if

    assert include_if("payload", "static", {"static", "all"}) == "payload"
    assert include_if("payload", "base", {"static", "all"}) is None
    assert include_if(42, "static", {"static"}) == 42
    assert include_if(None, "static", {"static"}) is None
    # Empty target set → never include.
    assert include_if("payload", "static", set()) is None
