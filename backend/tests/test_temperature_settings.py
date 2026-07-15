"""Tests for the temperature module's settings persistence.

Exercises the canonical four-endpoint settings surface mounted by
the registry. Verifies that ``unit``, ``sensor_colors`` and
``sample_period_ms`` round-trip through the atomic ``SettingsStore``
write.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.module_registry import ModuleRegistry


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
