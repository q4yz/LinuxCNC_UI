"""``/api/v1/settings`` on the system service."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.ui_settings_store import UiSettingsStore
from routers import ui_settings


@pytest.fixture()
def client(tmp_path):
    ui_settings.set_ui_settings_store(UiSettingsStore(tmp_path / "settings.json"))
    app = FastAPI()
    app.include_router(ui_settings.router)
    yield TestClient(app)
    ui_settings.set_ui_settings_store(None)


def test_list_is_empty_until_something_is_written(client):
    assert client.get("/api/v1/settings").json() == {"values": {}}


def test_write_echoes_the_stored_value_and_list_returns_it(client):
    resp = client.put("/api/v1/settings/temperature.unit", json={"value": "kelvin"})
    assert resp.status_code == 200
    assert resp.json() == {"key": "temperature.unit", "value": "kelvin"}
    assert client.get("/api/v1/settings").json() == {"values": {"temperature.unit": "kelvin"}}


def test_read_one_is_404_until_set(client):
    assert client.get("/api/v1/settings/camera.ip_camera_url").status_code == 404
    client.put("/api/v1/settings/camera.ip_camera_url", json={"value": "http://cam/stream"})
    resp = client.get("/api/v1/settings/camera.ip_camera_url")
    assert resp.status_code == 200
    assert resp.json()["value"] == "http://cam/stream"


def test_any_json_value_round_trips(client):
    value = {"cam0": {"rotate": 90, "mirror": True, "custom_name": "Spindle"}}
    client.put("/api/v1/settings/camera.preferences", json={"value": value})
    assert client.get("/api/v1/settings/camera.preferences").json()["value"] == value


def test_reset_removes_the_value(client):
    client.put("/api/v1/settings/temperature.unit", json={"value": "kelvin"})
    assert client.delete("/api/v1/settings/temperature.unit").status_code == 204
    assert client.get("/api/v1/settings/temperature.unit").status_code == 404
    assert client.delete("/api/v1/settings/temperature.unit").status_code == 204  # idempotent


def test_bad_key_is_400(client):
    assert client.put("/api/v1/settings/unit", json={"value": 1}).status_code == 400
    assert client.get("/api/v1/settings/Camera.url").status_code == 400


def test_missing_body_value_is_422(client):
    assert client.put("/api/v1/settings/temperature.unit", json={}).status_code == 422
