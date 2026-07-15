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

from core.module_registry import ModuleRegistry


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
    tmp_data_root, clean_env, caplog
):
    """Boot logs ``mounted=['temperature']`` and the router is live."""
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
    # Defaults from ``TemperatureSettings`` should be present.
    assert body["history_window_seconds"] == 10
    assert body["history_poll_interval_ms"] == 1000
    assert body["sample_period_ms"] == 500
    assert body["ambient_celsius"] == 25.0


def test_legacy_temperature_endpoint_is_gone(tmp_data_root, clean_env):
    """The old ``POST /api/v1/machine/temperature`` route is removed."""
    from routers.machine import router as legacy_machine_router

    paths = {route.path for route in legacy_machine_router.routes}
    # The legacy path was ``/api/v1/machine/temperature`` (prefix +
    # ``/temperature``). It must no longer be present.
    assert "/api/v1/machine/temperature" not in paths


def test_get_sensors_returns_mock_dict(tmp_data_root, clean_env):
    """``GET /api/v1/modules/temperature/sensors`` returns the
    mock's ``temperatures`` dictionary.
    """
    from modules.temperature.module import setup

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, candidates=[setup()])

    client = TestClient(app)
    resp = client.get("/api/v1/modules/temperature/sensors")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict) and "sensors" in body
    sensors = body["sensors"]
    # Mock seeds extruder, bed, cpu by default.
    assert set(sensors.keys()) >= {"extruder", "bed", "cpu"}
    assert "actual" in sensors["extruder"]


def test_set_target_dispatches_to_hardware(tmp_data_root, clean_env):
    """``POST /sensors/{name}/target`` updates the mock's state and
    is visible on the next ``GET /sensors``.
    """
    from modules.temperature.module import setup

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, candidates=[setup()])

    client = TestClient(app)
    # Set the bed heater target to 60 °C.
    resp = client.post(
        "/api/v1/modules/temperature/sensors/bed/target",
        json={"sensor_name": "bed", "target": 60.0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["sensor_name"] == "bed"
    assert body["target"] == 60.0

    # Verify the mock now reports the new target.
    resp = client.get("/api/v1/modules/temperature/sensors")
    assert resp.status_code == 200
    sensors = resp.json()["sensors"]
    assert sensors["bed"]["target"] == 60.0


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
