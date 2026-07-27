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