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
    # registry with the typed defaults from
    # :class:`ToolsSettings` (see ``.agent/contracts/backend-module.md``
    # § 1 — every module returns a non-null Pydantic model).
    resp = client.get("/api/v1/modules/tools/settings")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["confirm_spindle_start"] is False
    assert payload["max_spindle_rpm"] == 12000


def test_legacy_prefix_not_registered(tmp_data_root, clean_env):
    """The legacy flat-file ``POST /api/v1/machine/tools`` shape is
    not present on the new module router — Issue #64 ships the
    module router only. The historical ``GET /tools`` listing
    endpoint was superseded by the base-thread snapshot.
    """
    from modules.tools.module import setup
    from modules.tools.router import router as tools_router

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, candidates=[setup()])

    paths = {route.path for route in tools_router.routes}
    assert "/spindle" in paths
    assert "/extruder" in paths
    # ``POST /tools/{id}/target`` is the only remaining tool
    # endpoint on this router; ``GET /tools`` was retired in
    # favour of the base-thread snapshot.
    assert "/tools" not in paths
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
    from modules.tools import config_mapper

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
    monkeypatch.setattr(config_mapper, "_PROJECT_ROOT", tmp_path)
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
    from modules.tools import config_mapper

    _write_hardware_json(tmp_path, {
        "version": "2.0", "machine": "test",
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": "cartesian", "hal_type": "remora",
        "axes": [], "steppers": [], "drivers": [], "endstops": [],
        "tools": [], "temperature_sensors": [], "fans": [],
    })
    monkeypatch.setattr(config_mapper, "_PROJECT_ROOT", tmp_path)

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
    from modules.tools import config_mapper

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
    monkeypatch.setattr(config_mapper, "_PROJECT_ROOT", tmp_path)

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
    from modules.tools import config_mapper

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
    monkeypatch.setattr(config_mapper, "_PROJECT_ROOT", tmp_path)

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


def test_get_settings_model_returns_typed_model(tmp_data_root, clean_env):
    """The contract requires ``get_settings_model`` to return a
    non-null Pydantic ``BaseModel``. The tools module ships
    :class:`ToolsSettings` (introduced in the contract rewrite —
    see ``.agent/contracts/backend-module.md`` § 1) so the
    canonical four settings endpoints expose a typed payload from
    first boot.
    """
    from modules.tools.module import ToolsModule
    from modules.tools.settings import ToolsSettings

    instance = ToolsModule()
    model = instance.get_settings_model()
    assert isinstance(model, ToolsSettings)


def test_get_router_returns_apirouter(tmp_data_root, clean_env):
    from fastapi import APIRouter

    from modules.tools.module import ToolsModule

    instance = ToolsModule()
    router = instance.get_router()
    assert isinstance(router, APIRouter)
    # The historical ``GET /tools`` listing endpoint was superseded
    # by the base-thread snapshot, which is now the only public
    # surface for the tool list. Only the MDI and target-setter
    # routes remain on this router.
    paths = {route.path for route in router.routes}
    assert "/spindle" in paths
    assert "/extruder" in paths
    assert "/tools" not in paths
    assert "/tools/{tool_id}/target" in paths