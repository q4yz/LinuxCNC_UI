"""Tests for the temperature module's settings persistence.

Exercises the canonical four-endpoint settings surface mounted by
the registry. Verifies that ``history_window_seconds`` round-trips
through the atomic ``SettingsStore`` write.
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
        "history_window_seconds": 10,
        "history_poll_interval_ms": 1000,
    }


def test_put_settings_persists_new_history_window(tmp_data_root, clean_env):
    app, _ = _app(tmp_data_root)
    client = TestClient(app)
    resp = client.put(
        "/api/v1/modules/temperature/settings",
        json={"history_window_seconds": 30},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["history_window_seconds"] == 30
    # Defaults are still merged underneath the persisted value.
    assert body["history_poll_interval_ms"] == 1000
    assert body["sample_period_ms"] == 500
    assert body["ambient_celsius"] == 25.0


def test_settings_round_trip_across_clients(tmp_data_root, clean_env):
    """Two clients writing through the same ``SettingsStore`` see
    the merged result on read.
    """
    app, _ = _app(tmp_data_root)
    client = TestClient(app)
    # First write sets history_window_seconds.
    client.put(
        "/api/v1/modules/temperature/settings",
        json={"history_window_seconds": 45},
    )
    # Second write upserts a different key without overwriting the
    # first.
    client.put(
        "/api/v1/modules/temperature/settings/history_poll_interval_ms",
        json=2000,
    )
    payload = client.get(
        "/api/v1/modules/temperature/settings",
    ).json()
    assert payload["history_window_seconds"] == 45
    assert payload["history_poll_interval_ms"] == 2000


def test_settings_survive_restart(tmp_data_root, clean_env):
    """Restart the registry on the same data root and verify the
    user-set ``history_window_seconds`` is still present.
    """
    app, _ = _app(tmp_data_root)
    client = TestClient(app)
    client.put(
        "/api/v1/modules/temperature/settings",
        json={"history_window_seconds": 30},
    )
    # New registry / new app instance on the same data root.
    app2, _ = _app(tmp_data_root)
    client2 = TestClient(app2)
    payload = client2.get(
        "/api/v1/modules/temperature/settings",
    ).json()
    assert payload["history_window_seconds"] == 30


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
        json={"history_window_seconds": 7},
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
            json={"history_window_seconds": 99},
        )
    assert expected.read_bytes() == before
    # No leftover temp file.
    leftovers = list(expected.parent.glob(".settings-*.json.tmp"))
    assert leftovers == []
