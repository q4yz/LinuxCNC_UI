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

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.module_registry import ModuleRegistry


# ---------------------------------------------------------------------- #
# Boot / router discovery                                                 #
# ---------------------------------------------------------------------- #


def test_tools_module_boots_and_registers_router(tmp_data_root, clean_env):
    """The tools module is discoverable and the registry mounts its
    router under ``/api/v1/modules/tools``.
    """
    from modules.tools.module import setup

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, candidates=[setup()])

    assert "tools" in reg.modules

    client = TestClient(app)
    # Confirm the canonical settings endpoints are mounted by the
    # registry (no Pydantic defaults model today → empty dict).
    resp = client.get("/api/v1/modules/tools/settings")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_legacy_prefix_not_registered(tmp_data_root, clean_env):
    """The legacy flat-file ``POST /api/v1/machine/tools`` shape is
    not present on the new module router — Issue #64 ships the
    module router only.
    """
    from modules.tools.module import setup
    from modules.tools.router import router as tools_router

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, candidates=[setup()])

    paths = {route.path for route in tools_router.routes}
    assert "/spindle" in paths
    assert "/extruder" in paths
    # New operator-facing endpoints landed with the dynamic-config
    # pass: ``GET /tools`` (list) + ``POST /tools/{id}/target``
    # (heating-tool target). Both must be registered.
    assert "/tools" in paths
    assert "/tools/{tool_id}/target" in paths
    # No legacy prefix.
    assert "/api/v1/machine/tools" not in paths


# ---------------------------------------------------------------------- #
# POST /spindle                                                           #
# ---------------------------------------------------------------------- #


def _build_app(tmp_data_root):
    from modules.tools.module import setup

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, candidates=[setup()])
    return app


def test_spindle_forward_emits_m3(tmp_data_root, clean_env):
    app = _build_app(tmp_data_root)
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


def test_spindle_backward_emits_m4(tmp_data_root, clean_env):
    app = _build_app(tmp_data_root)
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


def test_spindle_stop_emits_m5(tmp_data_root, clean_env):
    """The stop action ignores ``speed`` and emits ``M5``."""
    app = _build_app(tmp_data_root)
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


def test_spindle_rejects_unknown_action(tmp_data_root, clean_env):
    app = _build_app(tmp_data_root)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/spindle",
        json={"tool_id": "spindle_main", "action": "sideways", "speed": 0},
    )
    assert resp.status_code == 400


def test_spindle_validates_speed_upper_bound(tmp_data_root, clean_env):
    app = _build_app(tmp_data_root)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/spindle",
        json={"tool_id": "spindle_main", "action": "forward", "speed": 999_999},
    )
    assert resp.status_code == 422


def test_spindle_validates_empty_tool_id(tmp_data_root, clean_env):
    app = _build_app(tmp_data_root)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/spindle",
        json={"tool_id": "", "action": "forward", "speed": 1000},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------- #
# POST /extruder                                                          #
# ---------------------------------------------------------------------- #


def test_extruder_extrude_emits_positive_distance(tmp_data_root, clean_env):
    app = _build_app(tmp_data_root)
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


def test_extruder_retract_inverts_distance_sign(tmp_data_root, clean_env):
    """Retract must apply a negative sign so the same positive
    ``distance`` value drives the extruder backwards.
    """
    app = _build_app(tmp_data_root)
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


def test_extruder_rejects_unknown_action(tmp_data_root, clean_env):
    app = _build_app(tmp_data_root)
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


def test_extruder_validates_distance_lower_bound(tmp_data_root, clean_env):
    """Negative or zero distances must be rejected — the router
    applies its own sign for retract, so callers should never
    hand a negative value through.
    """
    app = _build_app(tmp_data_root)
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


def test_get_tools_returns_empty_when_no_hardware_json(
    tmp_data_root, clean_env, monkeypatch, tmp_path
):
    """``GET /tools`` returns ``{ tools: [] }`` with 200 when no
    ``hardware.json`` is present — mirrors the temperature module's
    empty-sensor behaviour so the ToolPanel renders the "No tools
    configured yet" placeholder instead of failing to mount.
    """
    import json
    from pathlib import Path

    from services import tools_loader

    # Point the loader at a directory with no hardware.json so
    # the router sees the missing-file case.
    empty = tmp_path / "empty_active"
    empty.mkdir()
    monkeypatch.setattr(tools_loader, "_PROJECT_ROOT", empty)
    # ``tools_loader`` resolves via ``Path(__file__).parents[2]``;
    # patch the helper's ``_PROJECT_ROOT`` so the resolved path
    # has no hardware.json to read.
    monkeypatch.setattr(
        tools_loader, "_PROJECT_ROOT", tmp_path / "no_repo"
    )

    app = _build_app(tmp_data_root)
    client = TestClient(app)
    resp = client.get("/api/v1/modules/tools/tools")
    assert resp.status_code == 200
    assert resp.json() == {"tools": []}


def test_get_tools_returns_hardware_json_records(
    tmp_data_root, clean_env, monkeypatch, tmp_path
):
    """``GET /tools`` returns the ``tools[]`` array from the active
    ``hardware.json`` overlaid with runtime state. Extruder +
    heated_bed surfaces ``actual`` / ``target`` from the mock's
    sensor dict; spindle_digital surfaces ``actual_rpm`` from
    ``spindle_actual``; spindle_analog passes through unchanged.
    """
    from hardware import linuxcnc_mock
    from services import tools_loader

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
            {
                "id": "heater_bed",
                "type": "heated_bed",
                "sensor": "bed",
                "heater_pin": "PB7",
                "control": "watermark",
                "min_temp": 0,
                "max_temp": 130,
            },
            {
                "id": "spindle_digital",
                "type": "spindle_digital",
                "min_rpm": 5000,
                "max_rpm": 24000,
                "signal_at_speed": "at-speed1",
            },
            {
                "id": "spindle_analog",
                "type": "spindle_analog",
                "pwm_pin": "PA6",
                "enable_pin": "PA7",
                "min_rpm": 0,
                "max_rpm": 24000,
            },
        ],
        "temperature_sensors": [
            {"id": "extruder", "pin": "PA1"},
            {"id": "bed", "pin": "PA0"},
        ],
        "fans": [],
    }
    _write_hardware_json(tmp_path, hardware_payload)
    # The mock's seeder reads via its own path resolution — patch
    # its PROJECT_ROOT too so reseed_from_hardware_json() picks up
    # the fixture above.
    monkeypatch.setattr(
        "hardware.linuxcnc_mock._PROJECT_ROOT", tmp_path
    )
    linuxcnc_mock.reseed_from_hardware_json()
    # Patch the tools loader's project root as well so the
    # router reads from the fixture.
    monkeypatch.setattr(tools_loader, "_PROJECT_ROOT", tmp_path)

    # Mutate the mock's sensor / spindle state so the overlay
    # surfaces non-default values (proves the runtime read path,
    # not the default-zero fallback).
    with linuxcnc_mock._machine_state.lock:
        linuxcnc_mock._machine_state.temperatures["extruder"] = {
            "actual": 198.5, "target": 210.0,
        }
        linuxcnc_mock._machine_state.temperatures["bed"] = {
            "actual": 60.0, "target": 65.0,
        }
        linuxcnc_mock._machine_state.spindle_actual["spindle_digital"] = {
            "actual": 11800,
        }

    app = _build_app(tmp_data_root)
    client = TestClient(app)
    resp = client.get("/api/v1/modules/tools/tools")
    assert resp.status_code == 200
    tools_by_id = {t["id"]: t for t in resp.json()["tools"]}
    assert set(tools_by_id.keys()) == {
        "heater_extruder", "heater_bed",
        "spindle_digital", "spindle_analog",
    }
    # Heating tool runtime overlay.
    assert tools_by_id["heater_extruder"]["actual"] == 198.5
    assert tools_by_id["heater_extruder"]["target"] == 210.0
    assert tools_by_id["heater_bed"]["actual"] == 60.0
    assert tools_by_id["heater_bed"]["target"] == 65.0
    # Digital spindle runtime overlay.
    assert tools_by_id["spindle_digital"]["actual_rpm"] == 11800
    # Analog spindle: no runtime overlay — ``actual_rpm`` is absent.
    assert "actual_rpm" not in tools_by_id["spindle_analog"]
    # Static fields pass through unchanged.
    assert tools_by_id["spindle_digital"]["min_rpm"] == 5000
    assert tools_by_id["spindle_digital"]["max_rpm"] == 24000


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
    from services import tools_loader

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
    monkeypatch.setattr(
        "hardware.linuxcnc_mock._PROJECT_ROOT", tmp_path
    )
    monkeypatch.setattr(tools_loader, "_PROJECT_ROOT", tmp_path)
    linuxcnc_mock.reseed_from_hardware_json()

    app = _build_app(tmp_data_root)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/tools/heater_extruder/target",
        json={"tool_id": "heater_extruder", "target": 195.0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "status": "success",
        "tool_id": "heater_extruder",
        "target": 195.0,
        "sensor": "extruder",
    }
    # The mock's sensor dict now reflects the new target.
    with linuxcnc_mock._machine_state.lock:
        assert linuxcnc_mock._machine_state.temperatures["extruder"]["target"] == 195.0


def test_set_tool_target_rejects_unknown_tool(
    tmp_data_root, clean_env, monkeypatch, tmp_path
):
    """A tool id not declared in ``hardware.json`` is rejected
    with ``404`` so a frontend typo surfaces as a structured
    error instead of a silent no-op.
    """
    from services import tools_loader

    _write_hardware_json(tmp_path, {
        "version": "2.0", "machine": "test",
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": "cartesian", "hal_type": "remora",
        "axes": [], "steppers": [], "drivers": [], "endstops": [],
        "tools": [], "temperature_sensors": [], "fans": [],
    })
    monkeypatch.setattr(tools_loader, "_PROJECT_ROOT", tmp_path)

    app = _build_app(tmp_data_root)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/tools/heater_unknown/target",
        json={"tool_id": "heater_unknown", "target": 100.0},
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
    from services import tools_loader

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
    monkeypatch.setattr(tools_loader, "_PROJECT_ROOT", tmp_path)

    app = _build_app(tmp_data_root)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/tools/spindle_digital/target",
        json={"tool_id": "spindle_digital", "target": 100.0},
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
    from services import tools_loader

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
    monkeypatch.setattr(tools_loader, "_PROJECT_ROOT", tmp_path)

    app = _build_app(tmp_data_root)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/tools/tools/heater_extruder/target",
        json={"tool_id": "heater_extruder", "target": 999.0},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------- #
# Module lifecycle / factory contract (mirrors test_temperature_module).  #
# ---------------------------------------------------------------------- #


def test_setup_returns_fresh_tools_module(tmp_data_root, clean_env):
    """``setup()`` returns a fresh :class:`ToolsModule` and two
    calls produce independent instances.
    """
    from modules.tools.module import ToolsModule, setup

    instance = setup()
    assert isinstance(instance, ToolsModule)
    assert instance is not setup()


def test_setup_returns_isolated_instances(tmp_data_root, clean_env):
    from modules.tools.module import setup

    a = setup()
    b = setup()
    assert a is not b
    a._scratch = {"marker": 1}
    assert not hasattr(b, "_scratch")


def test_on_load_executes_without_error(tmp_data_root, clean_env):
    from core.event_bus import EventBus
    from core.settings_store import SettingsStore
    from modules.tools.module import ToolsModule

    instance = ToolsModule()
    ctx = {
        # ``on_load`` is a no-op; it doesn't even read the context,
        # but we pass the canonical shape so the contract stays
        # honest if a future revision subscribes to events.
        "module_id": "tools",
        "event_bus": EventBus(),
        "settings": SettingsStore(
            module_id="tools",
            data_root=tmp_data_root,
            defaults=None,
        ),
    }
    # ``on_load`` takes the typed ``ModuleContext``; the mock
    # here uses the canonical attribute names. The contract only
    # requires it not to raise, so duck-typing the call is safe.
    instance.on_load(ctx)


def test_on_unload_executes_without_error(tmp_data_root, clean_env):
    from modules.tools.module import ToolsModule

    instance = ToolsModule()
    instance.on_unload()
    instance.on_unload()  # idempotent


def test_get_settings_model_returns_none(tmp_data_root, clean_env):
    """Issue #64 ships without a typed Pydantic defaults schema;
    ``get_settings_model`` must return ``None`` so the registry
    falls back to untyped JSON.
    """
    from modules.tools.module import ToolsModule

    instance = ToolsModule()
    assert instance.get_settings_model() is None


def test_get_router_returns_apirouter(tmp_data_root, clean_env):
    from fastapi import APIRouter

    from modules.tools.module import ToolsModule

    instance = ToolsModule()
    router = instance.get_router()
    assert isinstance(router, APIRouter)
    paths = {route.path for route in router.routes}
    assert "/spindle" in paths
    assert "/extruder" in paths
    assert "/tools" in paths
    assert "/tools/{tool_id}/target" in paths