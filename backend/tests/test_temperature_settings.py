"""Tests for the temperature module's settings persistence.

Exercises the canonical four-endpoint settings surface mounted by
the registry. Verifies that ``unit``, ``sensor_colors`` and
``sample_period_ms`` round-trip through the atomic ``SettingsStore``
write.

Also covers unit tests for the :class:`TemperatureSettings` Pydantic
model itself (issue #43 § 2): defaults match the documented values,
and every ``Field`` raises ``ValidationError`` when supplied an
out-of-bound value.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.module_registry import ModuleRegistry
from hardware.mock.linuxcnc_mock import mock_system
from hardware.mock.test_helpers.mock_helpers import reseed_mock_from_json
from modules.temperature.settings import TemperatureSettings
from modules.temperature.module import setup




def _app(tmp_data_root):
    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, candidates=[setup()])
    return app, reg


def _point_config_at(monkeypatch, active_dir):
    """Point the canonical loader at ``active_dir/hardware.json``.

    Replaces the historical
    ``monkeypatch.setattr(config_mapper, "_DEFAULT_ACTIVE_DIR", ...)``
    seam — the loader no longer exposes a module-level default
    directory; the seam is the :class:`HardwareConfigService`
    constructor's ``active_path`` arg (which expects the path to
    ``hardware.json`` itself, not its parent directory).
    """
    from services.hardware_config_service import HardwareConfigService

    hardware_json = Path(active_dir) / "hardware.json"
    original_init = HardwareConfigService.__init__

    def _init(self, active_path=None, repo_root=None):
        return original_init(
            self,
            active_path=active_path if active_path is not None else hardware_json,
            repo_root=repo_root,
        )

    monkeypatch.setattr(HardwareConfigService, "__init__", _init)

    # NEW: Explicitly seed the mock hardware using the test's JSON file!
    # No more string-based monkeypatching of globals!
    if hardware_json.exists():
        reseed_mock_from_json(hardware_json)
    else:
        # If there's no hardware.json in this test, ensure the mock is empty
        mock_system.internal_hal._components.clear()


def test_settings_defaults_are_returned(tmp_data_root, clean_env, monkeypatch):
    """The defaults surface shows an empty ``sensor_colors`` map when
    no active ``hardware.json`` is present (issue #97).

    The legacy triple ``extruder/bed/cpu`` no longer hard-cures the
    defaults — colours are seeded from the active heater list.
    Without a fixture, the mock reports zero heaters and the seeded
    palette is therefore empty.
    """
    empty_dir = tmp_data_root / "no_active"
    empty_dir.mkdir()

    # This automatically clears the mock since there is no JSON file here
    _point_config_at(monkeypatch, empty_dir)

    app, _ = _app(tmp_data_root)
    client = TestClient(app)
    resp = client.get("/api/v1/modules/temperature/settings")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload == {
        "sample_period_ms": 500,
        "ambient_celsius": 25.0,
        "unit": "celsius",
        "sensor_colors": {},
    }


def test_settings_defaults_seed_from_active_heaters(
    tmp_data_root, clean_env, monkeypatch
):
    """The defaults surface seeds ``sensor_colors`` from the active
    heater list with the documented 6-colour palette (issue #97).

    A test fixture drops a ``hardware.json`` with three heaters; the
    alphabetical sort maps them to the first three palette entries
    (the 6-colour palette wraps modulo N).
    """
    active_dir = tmp_data_root / "machine_config" / "active"
    active_dir.mkdir(parents=True, exist_ok=True)
    (active_dir / "hardware.json").write_text(
        '{"temperature_sensors": ['
        '{"id": "chamber"}, '
        '{"id": "extruder"}, '
        '{"id": "heater_bed"}'
        "]}",
        encoding="utf-8",
    )

    # This automatically seeds the mock from the JSON file created above!
    _point_config_at(monkeypatch, active_dir)

    app, _ = _app(tmp_data_root)
    client = TestClient(app)
    resp = client.get("/api/v1/modules/temperature/settings")
    assert resp.status_code == 200
    body = resp.json()
    # Alphabetical sort: chamber, extruder, heater_bed.
    assert body["sensor_colors"] == {
        "chamber": "#EF4444",
        "extruder": "#3B82F6",
        "heater_bed": "#10B981",
    }


def test_put_settings_persists_new_unit(tmp_data_root, clean_env, monkeypatch):
    empty_dir = tmp_data_root / "no_active"
    empty_dir.mkdir()

    _point_config_at(monkeypatch, empty_dir)

    app, _ = _app(tmp_data_root)
    client = TestClient(app)
    resp = client.put(
        "/api/v1/modules/temperature/settings",
        json={"unit": "kelvin"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["unit"] == "kelvin"
    # Defaults are still merged underneath the persisted value.
    assert body["sample_period_ms"] == 500
    assert body["ambient_celsius"] == 25.0
    # Issue #97: defaults no longer hard-code the legacy triple.
    assert body["sensor_colors"] == {}


def test_settings_round_trip_across_clients(tmp_data_root, clean_env):
    """Two clients writing through the same ``SettingsStore`` see
    the merged result on read.
    """
    app, _ = _app(tmp_data_root)
    client = TestClient(app)
    # First write sets ``unit``.
    client.put(
        "/api/v1/modules/temperature/settings",
        json={"unit": "kelvin"},
    )
    # Second write upserts a different key without overwriting the
    # first.
    client.put(
        "/api/v1/modules/temperature/settings/sample_period_ms",
        json=750,
    )
    payload = client.get(
        "/api/v1/modules/temperature/settings",
    ).json()
    assert payload["unit"] == "kelvin"
    assert payload["sample_period_ms"] == 750


def test_settings_round_trip_sensor_colors(tmp_data_root, clean_env):
    """Per-sensor colours persist via the bulk PUT endpoint and are
    returned on subsequent reads.
    """
    app, _ = _app(tmp_data_root)
    client = TestClient(app)
    client.put(
        "/api/v1/modules/temperature/settings",
        json={"sensor_colors": {"extruder": "#000000", "chamber": "#FFFFFF"}},
    )
    payload = client.get(
        "/api/v1/modules/temperature/settings",
    ).json()
    # The two keys the user explicitly set round-trip verbatim.
    assert payload["sensor_colors"]["extruder"] == "#000000"
    assert payload["sensor_colors"]["chamber"] == "#FFFFFF"
    assert payload["sensor_colors"] == {
        "extruder": "#000000",
        "chamber": "#FFFFFF",
    }


def test_settings_round_trip_full_sensor_colors(tmp_data_root, clean_env):
    """When the caller sends the full map (as the frontend does),
    every key round-trips verbatim.
    """
    app, _ = _app(tmp_data_root)
    client = TestClient(app)
    payload = {
        "extruder": "#000000",
        "heater_bed": "#222222",
        "chamber": "#FFFFFF",
        "toolhead": "#123456",
    }
    client.put(
        "/api/v1/modules/temperature/settings",
        json={"sensor_colors": payload},
    )
    read = client.get(
        "/api/v1/modules/temperature/settings",
    ).json()
    assert read["sensor_colors"] == payload


def test_settings_survive_restart(tmp_data_root, clean_env):
    """Restart the registry on the same data root and verify the
    user-set ``unit`` is still present.
    """
    app, _ = _app(tmp_data_root)
    client = TestClient(app)
    client.put(
        "/api/v1/modules/temperature/settings",
        json={"unit": "kelvin"},
    )
    # New registry / new app instance on the same data root.
    app2, _ = _app(tmp_data_root)
    client2 = TestClient(app2)
    payload = client2.get(
        "/api/v1/modules/temperature/settings",
    ).json()
    assert payload["unit"] == "kelvin"


def test_settings_atomic_write_leaves_no_partial_file(
    tmp_data_root, clean_env, monkeypatch
):
    """Simulate an interrupted ``os.replace`` and confirm the
    previous ``settings.json`` survives intact.
    """
    import os
    from core import settings_store as ss_module

    app, _ = _app(tmp_data_root)
    client = TestClient(app)
    # Seed an existing settings file.
    client.put(
        "/api/v1/modules/temperature/settings",
        json={"unit": "celsius"},
    )

    # Compute the on-disk path of the temperature settings file.
    expected = tmp_data_root / "modules" / "temperature" / "settings.json"
    assert expected.exists()
    before = expected.read_bytes()

    real_replace = os.replace
    calls = {"count": 0}

    def boom(src, dst):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated crash")
        return real_replace(src, dst)

    monkeypatch.setattr(ss_module.os, "replace", boom)

    with pytest.raises(RuntimeError, match="simulated crash"):
        client.put(
            "/api/v1/modules/temperature/settings",
            json={"unit": "kelvin"},
        )
    assert expected.read_bytes() == before
    # No leftover temp file.
    leftovers = list(expected.parent.glob(".settings-*.json.tmp"))
    assert leftovers == []


# ---------------------------------------------------------------------------
# Unit tests for the ``TemperatureSettings`` Pydantic model
# ---------------------------------------------------------------------------

def test_temperature_settings_defaults_match_documented_values():
    model = TemperatureSettings()
    assert model.sample_period_ms == 500
    assert model.ambient_celsius == 25.0
    assert model.unit == "celsius"
    assert model.sensor_colors == {}


def test_temperature_settings_default_factory_isolates_instances():
    a = TemperatureSettings()
    b = TemperatureSettings()
    assert a.sensor_colors is not b.sensor_colors
    a.sensor_colors["chamber"] = "#000000"
    assert "chamber" not in b.sensor_colors


@pytest.mark.parametrize("value", [99, 5001])
def test_sample_period_ms_below_minimum_raises_validation_error(value):
    with pytest.raises(ValidationError) as excinfo:
        TemperatureSettings(sample_period_ms=value)
    assert "sample_period_ms" in str(excinfo.value)


@pytest.mark.parametrize("value", [100, 5000])
def test_sample_period_ms_boundary_values_are_accepted(value):
    model = TemperatureSettings(sample_period_ms=value)
    assert model.sample_period_ms == value


@pytest.mark.parametrize("value", [-50.1, -100.0, 100.1, 250.0])
def test_ambient_celsius_below_minimum_raises_validation_error(value):
    with pytest.raises(ValidationError) as excinfo:
        TemperatureSettings(ambient_celsius=value)
    assert "ambient_celsius" in str(excinfo.value)


@pytest.mark.parametrize("value", [-50.0, 100.0])
def test_ambient_celsius_boundary_values_are_accepted(value):
    model = TemperatureSettings(ambient_celsius=value)
    assert model.ambient_celsius == value


@pytest.mark.parametrize("value", ["celsius", "kelvin"])
def test_unit_accepts_documented_literal_values(value):
    model = TemperatureSettings(unit=value)
    assert model.unit == value


@pytest.mark.parametrize("value", ["Celsius", "KELVIN", "fahrenheit", "", "rankine"])
def test_unit_rejects_non_literal_values(value):
    with pytest.raises(ValidationError) as excinfo:
        TemperatureSettings(unit=value)
    assert "unit" in str(excinfo.value)


def test_sensor_colors_accepts_custom_mapping():
    payload = {"extruder": "#000000", "chamber": "#123456"}
    model = TemperatureSettings(sensor_colors=payload)
    assert model.sensor_colors == payload