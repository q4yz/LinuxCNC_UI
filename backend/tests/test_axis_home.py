"""Tests for the ``POST /home`` endpoint on the axis module.

Pins the contract for the axis module's homing facade after the
backend OOP refactor split the old monolithic machine module into
``modules/axis/``, ``modules/state/`` and ``modules/program/``. The
endpoint must:

* be reachable at ``POST /api/v1/modules/axis/home`` when mounted
  by the registry,
* delegate to :meth:`AxisService.home_single_axes` so the
  facade's ``MODE_MANUAL`` pre-switch + axis dispatch happens
  in one place (single-axis homing; ``axis == -1`` is forwarded to
  :meth:`AxisService.home_all_axes` inside the facade),
* keep the ``homeAxis`` operation_id so the regenerated OpenAPI
  client keeps ``ModulesAxisService.homeAxis`` on the frontend.
"""
from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.module_registry import ModuleRegistry


def _axis_app(tmp_data_root, clean_env):
    """Build a FastAPI app with the axis module booted."""
    from modules.axis.module import AxisModule

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, bus=EventBus(), candidates=[AxisModule()])
    return app, reg


def test_axis_home_endpoint_dispatches_to_facade(
    tmp_data_root, clean_env
):
    """``POST /home`` calls ``AxisService.home_single_axes``.

    We patch the facade method so the test runs hermetically
    without a live NML channel; the dispatch path is the contract
    we're pinning (the facade is responsible for the
    ``MODE_MANUAL`` pre-switch and the actual ``execute_sync_cmd``
    calls).
    """
    app, _ = _axis_app(tmp_data_root, clean_env)
    client = TestClient(app)

    with patch(
        "modules.axis.service.AxisService.home_single_axes"
    ) as mock_home:
        resp = client.post(
            "/api/v1/modules/axis/home",
            json={"axis": 2},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "success"}
    mock_home.assert_called_once_with(2)


def test_axis_home_endpoint_accepts_negative_axis(
    tmp_data_root, clean_env
):
    """``axis == -1`` (home all) is forwarded verbatim to the facade.

    The router does not interpret the sentinel — it only translates
    the HTTP edge; the facade decides what ``-1`` means
    (:meth:`AxisService.home_single_axes` delegates to
    :meth:`AxisService.home_all_axes` internally).
    """
    app, _ = _axis_app(tmp_data_root, clean_env)
    client = TestClient(app)

    with patch(
        "modules.axis.service.AxisService.home_single_axes"
    ) as mock_home:
        resp = client.post(
            "/api/v1/modules/axis/home",
            json={"axis": -1},
        )

    assert resp.status_code == 200
    mock_home.assert_called_once_with(-1)


def test_axis_home_endpoint_keeps_axis_tag():
    """``tags=["modules:axis"]`` keeps ``homeAxis`` under
    ``ModulesAxisService`` in the regenerated frontend client.

    Pinning the tag prevents an accidental future edit that
    renames the operation out of the axis service.
    """
    from modules.axis.router import router as axis_router

    routes = {route.path: route for route in axis_router.routes}
    home_route = routes["/home"]

    assert home_route.tags == ["modules:axis"]
    assert home_route.operation_id == "homeAxis"


def test_axis_home_endpoint_requires_axis_field(
    tmp_data_root, clean_env
):
    """Missing ``axis`` field → 422 (Pydantic validation).

    The handler signature is ``cmd: _HomeCommand`` so FastAPI
    enforces the schema before the function body runs.
    """
    app, _ = _axis_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.post("/api/v1/modules/axis/home", json={})
    assert resp.status_code == 422