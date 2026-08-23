"""Tests for the tools backend module (Issue #64).

Covers:

* Boot-time discovery + router mounting under
  ``/api/v1/modules/tools``.
* ``POST /spindle`` issues the right M3/M4/M5 string for each
  action and rejects unknown actions with ``400``.
* ``POST /extruder`` issues ``G91`` → ``G1 E{dist} F{speed}`` →
  ``G90``, signs ``dist`` correctly for retract, and rejects
  unknown actions with ``400``.
* Pydantic validators reject out-of-range speeds / distances with
  ``422``.
* The module's lifecycle / factory contract (mirrors
  ``test_temperature_module.py`` for consistency).
"""
from __future__ import annotations
from tests._module_app_factory import build_module_app

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------- #
# Active-root injection                                                   #
# ---------------------------------------------------------------------- #

def _point_config_at_tmp(monkeypatch, tmp_path):
    """Point :class:`HardwareConfigService` at ``tmp_path``.

    The test fixtures write ``hardware.json`` under
    ``tmp_path/machine_config/active/``; this helper patches
    :class:`HardwareConfigService.__init__` so every instance
    constructed by the production code under test resolves its
    active path against ``tmp_path`` (and not against the real
    ``machine_config/active/hardware.json``).

    Replaces the historical
    ``monkeypatch.setattr(config_mapper, "_PROJECT_ROOT", tmp_path)``
    seam — the loader no longer exposes a module-level
    ``_PROJECT_ROOT``; the seam is now the
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

# ---------------------------------------------------------------------- #
# Boot / router discovery                                                 #
# ---------------------------------------------------------------------- #

def _build_app(tmp_data_root, monkeypatch=None, tmp_path=None):
    """Build a tools-only FastAPI app with a fixture ``hardware.json``.

    Mirrors the historical build but skips the module registry —
    the tools router is mounted directly under ``/api/v1/modules/tools``
    by :func:`build_module_app`. The ``HardwareConfigService``
    monkeypatch ensures the loader resolves the configured tools from
    the test fixture rather than from the dev environment.
    """
    from fastapi import FastAPI
    from routers import _module_settings_router as msr
    from core.settings_store import SettingsStore
    from models.tools_settings import ToolsSettings

    if monkeypatch is not None and tmp_path is not None:
        active_dir = tmp_path / "machine_config" / "active"
        active_dir.mkdir(parents=True, exist_ok=True)
        hardware_json = active_dir / "hardware.json"
        if not hardware_json.exists():
            import json
            hardware_json.write_text(
                json.dumps(
                    {
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
                                "id": "spindle_main",
                                "type": "spindle_digital",
                                "min_rpm": 0,
                                "max_rpm": 24000,
                            },
                            {
                                "id": "extruder_1",
                                "type": "extruder",
                                "sensor": "extruder_1",
                                "heater_pin": "PE3",
                                "control": "pid",
                                "min_temp": 0,
                                "max_temp": 250,
                            },
                            {
                                "id": "heater_extruder",
                                "type": "extruder",
                                "sensor": "extruder",
                                "heater_pin": "PE3",
                                "control": "pid",
                                "min_temp": 0,
                                "max_temp": 250,
                            },
                        ],
                        "temperature_sensors": [
                            {"id": "extruder_1", "pin": "PA1"},
                            {"id": "extruder", "pin": "PA1"},
                        ],
                        "fans": [],
                    }
                ),
                encoding="utf-8",
            )

        from services.HardwareConfigService import HardwareConfigService
        original_init = HardwareConfigService.__init__

        def _init(self, active_path=None, repo_root=None):
            return original_init(
                self,
                active_path=(
                    active_path if active_path is not None else hardware_json
                ),
                repo_root=repo_root,
            )

        monkeypatch.setattr(HardwareConfigService, "__init__", _init)

    # Build the router manually because we need extra control over
    # the SettingsStore defaults (the canonical helper instantiates
    # a fresh store; tests that share state need the store reset
    # between calls).
    app = FastAPI()
    settings = SettingsStore(
        module_id="tools",
        data_root=tmp_data_root,
        defaults=ToolsSettings(),
    )
    app.include_router(
        msr.build_module_settings_router(settings),
        prefix="/api/v1/modules/tools/settings",
        tags=["modules:tools:settings"],
    )
    from routers import tools as tools_router
    app.include_router(tools_router.router)
    return app



def test_spindle_forward_emits_m3(tmp_data_root, clean_env, monkeypatch, tmp_path):
    app = _build_app(tmp_data_root, monkeypatch, tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/spindle",
        json={"tool_id": "spindle_main", "action": "forward", "speed": 12000},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "status": "success",
        "command": "M3 S12000",
        "tool_id": "spindle_main",
    }

def test_spindle_backward_emits_m4(tmp_data_root, clean_env, monkeypatch, tmp_path):
    app = _build_app(tmp_data_root, monkeypatch, tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/spindle",
        json={"tool_id": "spindle_main", "action": "backward", "speed": 8000},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "status": "success",
        "command": "M4 S8000",
        "tool_id": "spindle_main",
    }

def test_spindle_stop_emits_m5(tmp_data_root, clean_env, monkeypatch, tmp_path):
    """The stop action ignores ``speed`` and emits ``M5``."""
    app = _build_app(tmp_data_root, monkeypatch, tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/spindle",
        json={"tool_id": "spindle_main", "action": "stop", "speed": 0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "status": "success",
        "command": "M5",
        "tool_id": "spindle_main",
    }

def test_spindle_rejects_unknown_action(tmp_data_root, clean_env, monkeypatch, tmp_path):
    app = _build_app(tmp_data_root, monkeypatch, tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/spindle",
        json={"tool_id": "spindle_main", "action": "sideways", "speed": 0},
    )
    assert resp.status_code == 400

def test_spindle_validates_speed_upper_bound(tmp_data_root, clean_env, monkeypatch, tmp_path):
    app = _build_app(tmp_data_root, monkeypatch, tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/spindle",
        json={"tool_id": "spindle_main", "action": "forward", "speed": 999_999},
    )
    assert resp.status_code == 422

def test_spindle_validates_empty_tool_id(tmp_data_root, clean_env, monkeypatch, tmp_path):
    app = _build_app(tmp_data_root, monkeypatch, tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/spindle",
        json={"tool_id": "", "action": "forward", "speed": 1000},
    )
    assert resp.status_code == 422

# ---------------------------------------------------------------------- #
# POST /extruder                                                          #
# ---------------------------------------------------------------------- #

def test_extruder_extrude_emits_positive_distance(tmp_data_root, clean_env, monkeypatch, tmp_path):
    app = _build_app(tmp_data_root, monkeypatch, tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/extruder",
        json={
            "tool_id": "extruder_1",
            "action": "extrude",
            "distance": 5.0,
            "speed": 300,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # The echoed command is the G1 line itself; G91/G90 are
    # auxiliary framing M-codes that aren't part of the response
    # payload (Issue #64 § 1 behaviour).
    assert body["status"] == "success"
    assert body["command"] == "G1 E5.0 F300"
    assert body["tool_id"] == "extruder_1"

def test_extruder_retract_inverts_distance_sign(tmp_data_root, clean_env, monkeypatch, tmp_path):
    """Retract must apply a negative sign so the same positive
    ``distance`` value drives the extruder backwards.
    """
    app = _build_app(tmp_data_root, monkeypatch, tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/extruder",
        json={
            "tool_id": "extruder_1",
            "action": "retract",
            "distance": 2.5,
            "speed": 200,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["command"] == "G1 E-2.5 F200"

def test_extruder_rejects_unknown_action(tmp_data_root, clean_env, monkeypatch, tmp_path):
    app = _build_app(tmp_data_root, monkeypatch, tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/extruder",
        json={
            "tool_id": "extruder_1",
            "action": "sideways",
            "distance": 1.0,
            "speed": 100,
        },
    )
    assert resp.status_code == 400

def test_extruder_validates_distance_lower_bound(tmp_data_root, clean_env, monkeypatch, tmp_path):
    """Negative or zero distances must be rejected — the router
    applies its own sign for retract, so callers should never
    hand a negative value through.
    """
    app = _build_app(tmp_data_root, monkeypatch, tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/extruder",
        json={
            "tool_id": "extruder_1",
            "action": "extrude",
            "distance": -1.0,
            "speed": 100,
        },
    )
    assert resp.status_code == 422

# ---------------------------------------------------------------------- #
# GET /tools — operator-facing tool list                                  #
# ---------------------------------------------------------------------- #

def _write_hardware_json(tmp_path, payload):
    """Drop a v2-shape ``hardware.json`` into the active dir."""
    import json
    from pathlib import Path

    active_dir = Path(tmp_path) / "machine_config" / "active"
    active_dir.mkdir(parents=True, exist_ok=True)
    (active_dir / "hardware.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return active_dir

# The historical ``GET /tools`` listing endpoint was superseded by
# the base-thread snapshot (``GET /api/v1/base-thread/snapshot``),
# which is now the only public surface for the tool list. The legacy
# GET tests moved to ``test_base_thread_snapshot.py``.

# ---------------------------------------------------------------------- #
# POST /tools/{id}/target — heating-tool target dispatch                   #
# ---------------------------------------------------------------------- #

def test_set_tool_target_dispatches_set_temperature(
    tmp_data_root, clean_env, monkeypatch, tmp_path
):
    """``POST /tools/{id}/target`` looks up the tool's ``sensor``
    reference and dispatches ``set_temperature`` to the hardware
    layer. The response echoes the tool id, target, and resolved
    sensor.
    """
    from hardware import linuxcnc_mock
    import tools_config_mapper

    hardware_payload = {
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
                "id": "heater_extruder",
                "type": "extruder",
                "sensor": "extruder",
                "heater_pin": "PE3",
                "control": "pid",
                "min_temp": 0,
                "max_temp": 250,
            },
        ],
        "temperature_sensors": [
            {"id": "extruder", "pin": "PA1"},
        ],
        "fans": [],
    }
    _write_hardware_json(tmp_path, hardware_payload)
    _point_config_at_tmp(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "hardware.linuxcnc_mock._PROJECT_ROOT", tmp_path
    )
    reseed_from_hardware_json()

    app = _build_app(tmp_data_root, monkeypatch, tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/tools/heater_extruder/target",
        json={"id": "heater_extruder", "target": 195.0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["id"] == "heater_extruder"
    assert body["target"] == 195.0
    assert body["sensor"] == "extruder"
    # The mock's sensor dict now reflects the new target.
    from hardware.Connection import read_temperature

    reading = read_temperature("extruder")
    assert reading is not None and reading["target"] == 195.0

def test_set_tool_target_rejects_unknown_tool(
    tmp_data_root, clean_env, monkeypatch, tmp_path
):
    """A tool id not declared in ``hardware.json`` is rejected
    with ``404`` so a frontend typo surfaces as a structured
    error instead of a silent no-op.
    """
    _write_hardware_json(tmp_path, {
        "version": "2.0", "machine": "test",
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": "cartesian", "hal_type": "remora",
        "axes": [], "steppers": [], "drivers": [], "endstops": [],
        "tools": [], "temperature_sensors": [], "fans": [],
    })
    _point_config_at_tmp(monkeypatch, tmp_path)

    app = _build_app(tmp_data_root, monkeypatch, tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/tools/heater_unknown/target",
        json={"id": "heater_unknown", "target": 100.0},
    )
    assert resp.status_code == 404
    assert "heater_unknown" in resp.json()["detail"]

def test_set_tool_target_rejects_non_heating_tool(
    tmp_data_root, clean_env, monkeypatch, tmp_path
):
    """A spindle tool has no ``sensor`` reference and cannot accept
    a target. The router returns ``400`` with an actionable
    message instead of dispatching ``set_temperature`` on a
    ``None`` sensor.
    """
    _write_hardware_json(tmp_path, {
        "version": "2.0", "machine": "test",
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": "cartesian", "hal_type": "remora",
        "axes": [], "steppers": [], "drivers": [], "endstops": [],
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
    _point_config_at_tmp(monkeypatch, tmp_path)

    app = _build_app(tmp_data_root, monkeypatch, tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/tools/spindle_digital/target",
        json={"id": "spindle_digital", "target": 100.0},
    )
    assert resp.status_code == 400
    assert "spindle" in resp.json()["detail"].lower()

def test_set_tool_target_validates_range(
    tmp_data_root, clean_env, monkeypatch, tmp_path
):
    """The Pydantic ``Field(ge=0.0, le=400.0)`` rejects out-of-range
    targets with ``422`` — same contract as the temperature
    module's per-sensor endpoint.
    """
    _write_hardware_json(tmp_path, {
        "version": "2.0", "machine": "test",
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": "cartesian", "hal_type": "remora",
        "axes": [], "steppers": [], "drivers": [], "endstops": [],
        "tools": [
            {
                "id": "heater_extruder",
                "type": "extruder",
                "sensor": "extruder",
                "heater_pin": "PE3",
                "control": "pid",
            },
        ],
        "temperature_sensors": [{"id": "extruder", "pin": "PA1"}],
        "fans": [],
    })
    _point_config_at_tmp(monkeypatch, tmp_path)

    app = _build_app(tmp_data_root, monkeypatch, tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/tools/heater_extruder/target",
        json={"id": "heater_extruder", "target": 999.0},
    )
    assert resp.status_code == 422

# ---------------------------------------------------------------------- #
# Module lifecycle / factory contract (mirrors test_temperature_module).  #
# ---------------------------------------------------------------------- #

def test_get_spindle_state_endpoint_returns_full_dict(tmp_data_root, clean_env, monkeypatch):
    """``GET /spindle/{tool_id}`` returns the live telemetry.

    After ``M3 S{12000}`` the operator expects
    ``actual_rpm`` / ``is_connected`` / ``error_count`` to populate
    from the mock simulator rather than stay at the seeded defaults.
    The endpoint surfaces the same dict the base-thread snapshot
    carries, so a regression in either the simulator or the router
    surfaces here.
    """
    import json

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.event_bus import EventBus
    from core.module_registry import ModuleRegistry
    from hardware import linuxcnc_mock

    # The mock ignores M-codes while the machine is in STATE_ESTOP
    # (which is the boot default). Flip it to STATE_ON so the
    # ``M3 S12000`` dispatch lands.
    set_mock_task_state(StateMachineMock.STATE_ON)

    # Seed a hardware.json with one ``spindle_digital`` so the
    # spindle loader has something to enumerate.
    from hardware import linuxcnc_mock as hw_mock
    active_root = tmp_data_root / "machine_config" / "active"
    active_root.mkdir(parents=True, exist_ok=True)
    (active_root / "hardware.json").write_text(
        json.dumps(
            {
                "tools": [
                    {
                        "type": "spindle_digital",
                        "id": "spindle_digital",
                        "signal_spindle_at_speed": "spindle.0.at-speed",
                        "signal_target_rpm": "spindle.0.target-rpm",
                        "signal_actual_out": "spindle.0.rpm-out",
                        "signal_is_connected": "spindle.0.on",
                        "signal_error_count": "spindle.0.error-count",
                        "signal_last_error": "spindle.0.last-error",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _point_config_at_tmp(monkeypatch, tmp_data_root)
    monkeypatch.setattr(hw_mock, "_PROJECT_ROOT", tmp_data_root)
    hw_mock.reseed_from_hardware_json()
    app.include_router(tools_router.router)
    client = TestClient(app)

    # The mock seeds every spindle with default zeros. Ramp the
    # spindle_main to 12000 RPM via the canonical POST /spindle
    # endpoint so the service pushes a new target into the simulator.
    r = client.post(
        "/api/v1/modules/tools/spindle",
        json={
            "tool_id": "spindle_digital",
            "action": "forward",
            "speed": 12000,
        },
    )
    assert r.status_code == 200, r.text

    # Read live state via the new GET endpoint.
    r = client.get("/api/v1/modules/tools/spindle/spindle_digital")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == "spindle_digital"
    # ``is_connected`` flips True on the operator's action — the
    # endpoint surfaces the eagerly-updated dict, not the simulator
    # polling rate. The HAL poll loop refines ``actual_rpm`` over the
    # next ~2 s; the test environment does not run the poll thread,
    # so we assert on the bits that don't depend on it.
    assert body["is_connected"] is True
    assert body["error_count"] == 0

def test_get_spindle_state_endpoint_returns_404_for_unknown_id(
    tmp_data_root, clean_env,
):
    """Unknown spindle id → 404 with a clear operator-facing message.

    Mirrors the historical behaviour of ``control_spindle`` and
    ``set_spindle_speed``: a typo in the URL must not silently return
    default zeros — the operator (or a future curl helper) needs to
    know the id was unknown.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.event_bus import EventBus
    from core.module_registry import ModuleRegistry
    app.include_router(tools_router.router)
    client = TestClient(app)

    r = client.get("/api/v1/modules/tools/spindle/no-such-spindle")
    assert r.status_code == 404
    assert "no-such-spindle" in r.json()["detail"]

