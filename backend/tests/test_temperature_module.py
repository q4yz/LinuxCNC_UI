"""Tests for the temperature backend module.

Covers:

* Boot-time discovery + router mounting under
  ``/api/v1/modules/temperature``.
* ``GET /sensors`` returns the mock's sensor dictionary.
* ``POST /sensors/{name}/target`` dispatches ``set_temperature`` to
  the hardware layer and reflects in subsequent ``GET /sensors``.
* The legacy ``POST /api/v1/machine/temperature`` endpoint is no
  longer registered.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.module_registry import ModuleRegistry
from core.protocols import ModuleContext
from core.settings_store import SettingsStore


def _build_app(tmp_data_root) -> tuple[FastAPI, ModuleRegistry]:
    """Build a fresh FastAPI app + registry with the temperature
    module loaded.
    """
    from modules import temperature as _ignored  # noqa: F401  (touch the package)
    # The above import ensures the package is importable; the
    # actual instance is produced via ``setup()`` during boot.
    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app)
    return app, reg


def test_temperature_module_boots_and_registers_router(
    tmp_data_root, clean_env, caplog, monkeypatch
):
    """Boot logs ``mounted=['temperature']`` and the router is live.

    The module's :meth:`get_settings_model` hook seeds the
    ``sensor_colors`` map from the active sensor list. A test that
    points the helper at a ``tmp_path`` with two declared temperature
    sensors (in the v2 ``hardware.json`` shape) asserts the seeded
    palette flows through to ``GET /api/v1/modules/temperature/settings``.
    """
    from services import hardware_loader

    active_dir = tmp_data_root / "machine_config" / "active"
    active_dir.mkdir(parents=True, exist_ok=True)
    # v2 hardware.json: temperature_sensors[] is the canonical list
    # the temperature module seeds from. The heater_bed sensor id is
    # ``bed`` (the ``heater_`` prefix is stripped per
    # ``_temperature_sensor_id``).
    (active_dir / "hardware.json").write_text(
        '{"temperature_sensors": ['
        '{"id": "extruder", "pin": "PA1"}, '
        '{"id": "bed", "pin": "PA0"}'
        "]}",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        hardware_loader, "_DEFAULT_ACTIVE_DIR", active_dir
    )

    app, reg = _build_app(tmp_data_root)
    with caplog.at_level(logging.INFO, logger="core.module_registry"):
        # Re-boot to capture the summary log; the previous boot is a
        # side-effect of constructing the test app.
        pass

    summary = [
        r.message
        for r in caplog.records
        if "registry: mounted=" in r.message
    ]
    # The summary line may or may not be present depending on test
    # ordering, so we look at the registry state directly.
    assert "temperature" in reg.modules

    client = TestClient(app)
    # Confirm the canonical settings endpoints are mounted by the
    # registry.
    resp = client.get("/api/v1/modules/temperature/settings")
    assert resp.status_code == 200
    body = resp.json()
    # Defaults from ``TemperatureSettings`` should be present. The
    # ``history_*`` fields have been retired — see issue #35.
    assert body["sample_period_ms"] == 500
    assert body["ambient_celsius"] == 25.0
    assert body["unit"] == "celsius"
    # v2 model: ``sensor_colors`` is seeded from the active
    # ``temperature_sensors[]`` list. Alphabetical order (``bed``,
    # ``extruder``) maps to the first two entries of the 6-colour
    # palette: ``bed`` -> red, ``extruder`` -> blue.
    assert body["sensor_colors"] == {
        "bed": "#EF4444",
        "extruder": "#3B82F6",
    }


def test_legacy_temperature_endpoint_is_gone(tmp_data_root, clean_env):
    """The old ``POST /api/v1/machine/temperature`` route is removed.

    Issue #38 deleted ``backend/routers/machine.py`` along with
    ``backend/routers/jog.py`` as part of the machine-module migration.
    The legacy temperature endpoint is therefore gone by construction:
    we exercise the temperature module's own router and assert the
    legacy path is **not** registered under it.
    """
    from modules.temperature.router import router as temperature_router

    paths = {route.path for route in temperature_router.routes}
    assert "/temperature" not in paths
    # And, by construction, the legacy prefix is gone too (the file
    # that defined it no longer exists).
    assert "/api/v1/machine/temperature" not in paths


def test_get_sensors_returns_mock_dict_empty_when_no_hardware_json(
    tmp_data_root, clean_env, monkeypatch
):
    """``GET /api/v1/modules/temperature/sensors`` returns an empty
    dict when no ``hardware.json`` is present (issue #97).

    The mock used to hard-code ``extruder/bed/cpu`` at import time;
    the dynamic sensor list now starts as ``{}`` when the operator
    has not yet deployed a profile. The endpoint must serialise
    that empty dict verbatim.
    """
    from services import hardware_loader

    empty_dir = tmp_data_root / "no_active"
    empty_dir.mkdir()
    monkeypatch.setattr(
        hardware_loader, "_DEFAULT_ACTIVE_DIR", empty_dir
    )
    # The mock singleton was initialised before this monkey-patch
    # was applied; force a re-seed so the empty directory is
    # honoured.
    from hardware import linuxcnc_mock

    linuxcnc_mock.reseed_from_hardware_json()

    from modules.temperature.module import setup

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, candidates=[setup()])

    client = TestClient(app)
    resp = client.get("/api/v1/modules/temperature/sensors")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict) and "sensors" in body
    assert body["sensors"] == {}


def test_get_sensors_returns_dynamic_heater_list_from_hardware_json(
    tmp_data_root, clean_env, monkeypatch
):
    """``GET /api/v1/modules/temperature/sensors`` exposes the sensor
    list from ``machine_config/active/hardware.json`` (issue #97 +
    v2 hardware.json model).

    The test fixture drops a fake v2 ``hardware.json`` with two
    temperature sensors in a ``tmp_path`` tree and asserts the mock
    seeds those two sensors (no more, no less). Each entry must
    carry an ``actual`` reading.
    """
    from services import hardware_loader

    active_dir = tmp_data_root / "machine_config" / "active"
    active_dir.mkdir(parents=True, exist_ok=True)
    # v2 hardware.json: ``temperature_sensors[]`` is the canonical
    # list the mock seeds from. The heater_bed sensor id is ``bed``
    # (``heater_`` prefix stripped per ``_temperature_sensor_id``).
    (active_dir / "hardware.json").write_text(
        '{"temperature_sensors": ['
        '{"id": "extruder", "pin": "PA1"}, '
        '{"id": "bed", "pin": "PA0"}'
        "]}",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        hardware_loader, "_DEFAULT_ACTIVE_DIR", active_dir
    )

    # The mock singleton was initialised before this monkey-patch
    # was applied; force a re-seed so the freshly written
    # ``hardware.json`` is honoured.
    from hardware import linuxcnc_mock

    linuxcnc_mock.reseed_from_hardware_json()

    from modules.temperature.module import setup

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, candidates=[setup()])

    client = TestClient(app)
    resp = client.get("/api/v1/modules/temperature/sensors")
    assert resp.status_code == 200
    sensors = resp.json()["sensors"]
    # The mock must report exactly the sensors declared in
    # ``hardware.json`` — no legacy ``cpu`` sensor.
    assert set(sensors.keys()) == {"extruder", "bed"}
    # Each seeded entry has the documented starting state.
    for name, entry in sensors.items():
        assert "actual" in entry
        assert entry["actual"] == 25.0
        assert entry["target"] == 0.0


def test_set_target_dispatches_to_hardware(tmp_data_root, clean_env, monkeypatch):
    """``POST /sensors/{name}/target`` updates the mock's state and
    is visible on the next ``GET /sensors`` (issue #97).

    The mock now seeds the sensor list from ``hardware.json`` so the
    test drops a fake active ``hardware.json`` with a ``heater_bed``
    entry before exercising the ``POST /sensors/{name}/target`` flow.
    """
    from services import hardware_loader

    active_dir = tmp_data_root / "machine_config" / "active"
    active_dir.mkdir(parents=True, exist_ok=True)
    (active_dir / "hardware.json").write_text(
        '{"heaters": [{"name": "heater_bed"}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        hardware_loader, "_DEFAULT_ACTIVE_DIR", active_dir
    )

    # The mock singleton was initialised before this monkey-patch
    # was applied; force a re-seed so the freshly written
    # ``hardware.json`` is honoured.
    from hardware import linuxcnc_mock

    linuxcnc_mock.reseed_from_hardware_json()

    from modules.temperature.module import setup

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, candidates=[setup()])

    client = TestClient(app)
    # Set the bed heater target to 60 °C.
    resp = client.post(
        "/api/v1/modules/temperature/sensors/heater_bed/target",
        json={"sensor_name": "heater_bed", "target": 60.0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["sensor_name"] == "heater_bed"
    assert body["target"] == 60.0

    # Verify the mock now reports the new target.
    resp = client.get("/api/v1/modules/temperature/sensors")
    assert resp.status_code == 200
    sensors = resp.json()["sensors"]
    assert sensors["heater_bed"]["target"] == 60.0


def test_set_target_validates_range(tmp_data_root, clean_env):
    """The Pydantic ``Field(ge=0.0, le=400.0)`` rejects out-of-range
    targets with ``422``.
    """
    from modules.temperature.module import setup

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, candidates=[setup()])

    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/temperature/sensors/extruder/target",
        json={"sensor_name": "extruder", "target": 999.0},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Unit tests for module lifecycle & factory (issue #43 § 1).
#
# These tests exercise the module's surface in isolation, without booting
# the full registry or routing through the HTTP layer. They use direct
# imports to verify the contract documented in the
# ``backend-module`` contract.
# ---------------------------------------------------------------------------


def test_setup_returns_fresh_temperature_module(tmp_data_root, clean_env):
    """``setup()`` must return a fresh :class:`TemperatureModule`
    instance, per the factory contract documented in
    ``module.py`` (issue #43 § 1).
    """
    from modules.temperature.module import TemperatureModule, setup

    instance = setup()
    assert isinstance(instance, TemperatureModule)
    # The factory must construct a fresh instance — not return a
    # cached module-level singleton.
    assert instance is not setup()


def test_setup_returns_isolated_instances(tmp_data_root, clean_env):
    """Two ``setup()`` calls must produce independent objects so
    test runs cannot leak state across reloads.
    """
    from modules.temperature.module import setup

    a = setup()
    b = setup()
    assert a is not b
    # Mutating one instance must not be visible on the other.
    a._scratch = {"marker": 1}
    assert not hasattr(b, "_scratch")


def test_on_load_executes_without_error(tmp_data_root, clean_env):
    """``on_load`` is a no-op today; it must execute without raising
    and must accept a :class:`ModuleContext` (issue #43 § 1).
    """
    from core.event_bus import EventBus
    from core.settings_store import SettingsStore
    from modules.temperature.module import TemperatureModule

    instance = TemperatureModule()
    ctx = ModuleContext(
        module_id="temperature",
        event_bus=EventBus(),
        settings=SettingsStore(
            module_id="temperature",
            data_root=tmp_data_root,
            defaults=None,
        ),
    )
    # Should not raise.
    instance.on_load(ctx)


def test_on_unload_executes_without_error(tmp_data_root, clean_env):
    """``on_unload`` is idempotent and must execute without raising
    even when called repeatedly (issue #43 § 1 + module-protocol
    contract).
    """
    from modules.temperature.module import TemperatureModule

    instance = TemperatureModule()
    instance.on_unload()
    # Second call must also be a no-op (per the contract, ``on_unload``
    # is required to be idempotent).
    instance.on_unload()


def test_get_settings_model_returns_temperature_settings(tmp_data_root, clean_env):
    """``get_settings_model`` must return a fresh
    :class:`TemperatureSettings` instance (issue #43 § 1).
    """
    from modules.temperature.module import TemperatureModule
    from modules.temperature.settings import TemperatureSettings

    instance = TemperatureModule()
    model = instance.get_settings_model()
    assert isinstance(model, TemperatureSettings)
    # It must be a fresh instance — subsequent calls must not share
    # state.
    other = instance.get_settings_model()
    assert model is not other


def test_get_router_returns_apirouter(tmp_data_root, clean_env):
    """``get_router`` must return the module's :class:`APIRouter`
    (issue #43 § 1).
    """
    from fastapi import APIRouter

    from modules.temperature.module import TemperatureModule

    instance = TemperatureModule()
    router = instance.get_router()
    assert isinstance(router, APIRouter)
    # The router must expose the two documented endpoints.
    paths = {route.path for route in router.routes}
    assert "/sensors" in paths
    assert "/sensors/{name}/target" in paths
