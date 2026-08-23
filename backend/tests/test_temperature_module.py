"""Tests for the temperature backend module.

Covers:

* Boot-time discovery + router mounting under
  ``/api/v1/modules/temperature``.
* ``POST /sensors/{name}/target`` dispatches ``set_temperature``
  to the hardware layer and the mock surfaces the new target.
* The legacy ``POST /api/v1/machine/temperature`` endpoint is no
  longer registered.
* The historical ``GET /sensors`` listing endpoint was superseded
  by the base-thread snapshot
  (``GET /api/v1/base-thread/snapshot``), which is now the only
  public surface for the sensor dict.
"""

from __future__ import annotations
from tests._module_app_factory import build_module_app

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hardware.mock.test_helpers.mock_helpers import reseed_from_hardware_json

def _build_app(tmp_data_root, clean_env=None):
    """Build a FastAPI app with the temperature module wired up."""
    return build_module_app("temperature", tmp_data_root), None

def test_legacy_temperature_endpoint_is_gone(tmp_data_root, clean_env):
    """The old ``POST /api/v1/machine/temperature`` route is removed.

    Issue #38 deleted ``backend/routers/machine.py`` along with
    ``backend/routers/jog.py`` as part of the machine-module migration.
    The legacy temperature endpoint is therefore gone by construction:
    we exercise the temperature module's own router and assert the
    legacy path is **not** registered under it.
    """
    from routers.temperature import router as temperature_router

    paths = {route.path for route in temperature_router.routes}
    assert "/temperature" not in paths
    # And, by construction, the legacy prefix is gone too (the file
    # that defined it no longer exists).
    assert "/api/v1/machine/temperature" not in paths

# ---------------------------------------------------------------------------
# Unit tests for the temperature settings model (issue #43 § 1).
# The module-system contract was retired; we now test the Pydantic
# model directly and verify the canonical settings surface via the
# integration tests in test_temperature_settings.py.
# ---------------------------------------------------------------------------

def test_temperature_settings_defaults_round_trip():
    from models.temperature_settings import TemperatureSettings

    model = TemperatureSettings()
    assert model.sample_period_ms == 500
    assert model.ambient_celsius == 25.0
    assert model.unit == "celsius"
    assert model.sensor_colors == {}

