from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from tests._module_app_factory import build_module_app


def _axis_app(tmp_data_root, clean_env=None):
    return build_module_app("axis", tmp_data_root), None


def test_axis_settings_endpoint_dispatches_to_facade(tmp_data_root, clean_env):
    app, _ = _axis_app(tmp_data_root, clean_env)
    client = TestClient(app)

    with patch("services.AxisService.AxisService.update_settings") as mock_update:
        resp = client.post(
            "/api/v1/modules/axis/settings",
            json={"multiplier": 1.25, "absolute_speed_limit": 3000},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "success"}
    mock_update.assert_called_once_with(1.25, 3000)


def test_axis_settings_endpoint_validates_bounds(tmp_data_root, clean_env):
    app, _ = _axis_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/modules/axis/settings",
        json={"multiplier": 7.0, "absolute_speed_limit": 1000},
    )
    assert resp.status_code == 422

    resp = client.post(
        "/api/v1/modules/axis/settings",
        json={"multiplier": 1.0, "absolute_speed_limit": 9000},
    )
    assert resp.status_code == 422


def test_axis_settings_endpoint_requires_fields(tmp_data_root, clean_env):
    app, _ = _axis_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/modules/axis/settings",
        json={"multiplier": 1.0},
    )
    assert resp.status_code == 422

    resp = client.post(
        "/api/v1/modules/axis/settings",
        json={"absolute_speed_limit": 1000},
    )
    assert resp.status_code == 422


def test_axis_service_update_settings_dispatches(tmp_data_root, clean_env):
    from services.AxisService import AxisService

    with patch("services.AxisService.execute_sync_cmd") as mock_exec:
        AxisService().update_settings(1.25, 3000)

    assert mock_exec.call_count == 2
    mock_exec.assert_any_call("feedrate", 0, 1.25)
    mock_exec.assert_any_call("maxvel", 0, 50.0)


def test_axis_settings_endpoint_keeps_axis_tag(tmp_data_root, clean_env):
    app, _ = _axis_app(tmp_data_root, clean_env)
    settings_route = next(
        route
        for route in app.router.routes
        if getattr(route, "path", None) == "/api/v1/modules/axis/settings"
        and "POST" in (getattr(route, "methods", None) or set())
    )
    assert "modules:axis" in (settings_route.tags or [])