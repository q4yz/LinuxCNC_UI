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
    import module_settings_router as msr
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




