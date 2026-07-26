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

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.module_registry import ModuleRegistry
from modules.temperature.settings import TemperatureSettings


def _app(tmp_data_root):
    from modules.temperature.module import setup

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, candidates=[setup()])
    return app, reg


def test_settings_defaults_are_returned(tmp_data_root, clean_env):
    app, _ = _app(tmp_data_root)
    client = TestClient(app)
    resp = client.get("/api/v1/modules/temperature/settings")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload == {
        "sample_period_ms": 500,
        "ambient_celsius": 25.0,
        "unit": "celsius",
        "sensor_colors": {
            "extruder": "#EF4444",
            "bed": "#3B82F6",
            "cpu": "#10B981",
        },
    }


def test_put_settings_persists_new_unit(tmp_data_root, clean_env):
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
    assert body["sensor_colors"] == {
        "extruder": "#EF4444",
        "bed": "#3B82F6",
        "cpu": "#10B981",
    }


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
    returned on subsequent reads. The store merges defaults
    underneath the persisted payload, so an explicit partial map
    fully replaces the default palette — this matches the
    ``SettingsStore._merge_defaults`` behaviour. The frontend
    always sends the complete map from the in-memory store, so the
    visual identity is preserved end-to-end.
    """
    app, _ = _app(tmp_data_root)
    client = TestClient(app)
    client.put(
        "/api/v1/modules/temperature/settings",
        json={"sensor_colors": {"extruder": "#000000", "cpu": "#FFFFFF"}},
    )
    payload = client.get(
        "/api/v1/modules/temperature/settings",
    ).json()
    # The two keys the user explicitly set round-trip verbatim.
    assert payload["sensor_colors"]["extruder"] == "#000000"
    assert payload["sensor_colors"]["cpu"] == "#FFFFFF"
    # The untouched key is gone — the user-supplied map fully
    # replaced the default palette at the top-level dict key. The
    # frontend always re-sends the merged map from memory so the
    # UI never drops a sensor by accident.
    assert "bed" not in payload["sensor_colors"]


def test_settings_round_trip_full_sensor_colors(tmp_data_root, clean_env):
    """When the caller sends the full map (as the frontend does),
    every key round-trips and the default palette is preserved for
    sensors not explicitly mentioned.
    """
    app, _ = _app(tmp_data_root)
    client = TestClient(app)
    payload = {
        "extruder": "#000000",
        "bed": "#222222",
        "cpu": "#FFFFFF",
        "chamber": "#123456",
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
    # The next PUT raises inside SettingsStore but the file is intact.
    import pytest

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
# Unit tests for the ``TemperatureSettings`` Pydantic model (issue #43 § 2).
#
# These tests construct the model directly (no HTTP layer) and exercise
# its defaults and ``Field`` boundary validators. They are independent of
# the registry/SettingsStore and therefore run fast.
# ---------------------------------------------------------------------------


def test_temperature_settings_defaults_match_documented_values():
    """Default values for every field must match the module's
    documented contract (issue #43 § 2):
    ``sample_period_ms=500``, ``ambient_celsius=25.0``,
    ``unit="celsius"``, plus the three default ``sensor_colors``.
    """
    model = TemperatureSettings()
    assert model.sample_period_ms == 500
    assert model.ambient_celsius == 25.0
    assert model.unit == "celsius"
    # The default colour map must contain the three documented
    # sensors.
    assert set(model.sensor_colors.keys()) == {"extruder", "bed", "cpu"}
    # And the values must be the expected hex strings.
    assert model.sensor_colors == {
        "extruder": "#EF4444",
        "bed": "#3B82F6",
        "cpu": "#10B981",
    }


def test_temperature_settings_default_factory_isolates_instances():
    """Calling the model constructor twice must produce two
    independent ``sensor_colors`` dicts — the default factory must
    not share a single reference across instances.
    """
    a = TemperatureSettings()
    b = TemperatureSettings()
    assert a.sensor_colors is not b.sensor_colors
    # Mutating one must not bleed into the other.
    a.sensor_colors["chamber"] = "#000000"
    assert "chamber" not in b.sensor_colors


@pytest.mark.parametrize("value", [99, 5001])
def test_sample_period_ms_below_minimum_raises_validation_error(value):
    """``sample_period_ms`` must enforce ``ge=100`` / ``le=5000``."""
    with pytest.raises(ValidationError) as excinfo:
        TemperatureSettings(sample_period_ms=value)
    # The error must mention the offending field.
    assert "sample_period_ms" in str(excinfo.value)


@pytest.mark.parametrize("value", [100, 5000])
def test_sample_period_ms_boundary_values_are_accepted(value):
    """The inclusive boundary values 100 and 5000 must be accepted."""
    model = TemperatureSettings(sample_period_ms=value)
    assert model.sample_period_ms == value


@pytest.mark.parametrize("value", [-50.1, -100.0, 100.1, 250.0])
def test_ambient_celsius_below_minimum_raises_validation_error(value):
    """``ambient_celsius`` must enforce ``ge=-50.0`` / ``le=100.0``."""
    with pytest.raises(ValidationError) as excinfo:
        TemperatureSettings(ambient_celsius=value)
    assert "ambient_celsius" in str(excinfo.value)


@pytest.mark.parametrize("value", [-50.0, 100.0])
def test_ambient_celsius_boundary_values_are_accepted(value):
    """The inclusive boundary values -50.0 and 100.0 must be accepted."""
    model = TemperatureSettings(ambient_celsius=value)
    assert model.ambient_celsius == value


@pytest.mark.parametrize("value", ["celsius", "kelvin"])
def test_unit_accepts_documented_literal_values(value):
    """Both ``"celsius"`` and ``"kelvin"`` are valid (issue #43 § 2)."""
    model = TemperatureSettings(unit=value)
    assert model.unit == value


@pytest.mark.parametrize("value", ["Celsius", "KELVIN", "fahrenheit", "", "rankine"])
def test_unit_rejects_non_literal_values(value):
    """Any value not in ``("celsius", "kelvin")`` must raise
    ``ValidationError`` — the ``Literal`` type rejects bad strings.
    """
    with pytest.raises(ValidationError) as excinfo:
        TemperatureSettings(unit=value)
    assert "unit" in str(excinfo.value)


def test_sensor_colors_accepts_custom_mapping():
    """A user-supplied ``sensor_colors`` dict must round-trip
    verbatim.
    """
    payload = {"extruder": "#000000", "chamber": "#123456"}
    model = TemperatureSettings(sensor_colors=payload)
    assert model.sensor_colors == payload
