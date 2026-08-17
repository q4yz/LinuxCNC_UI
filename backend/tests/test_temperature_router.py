"""Tests for the temperature module's HTTP tombstone router.

The router at :mod:`modules.temperature.router` is a 410 Gone tombstone
that intercepts legacy requests from older frontends and points them
at the canonical ``/tools/{id}/target`` endpoint. The live dispatch
itself lives on the tools module (covered in ``test_tools_module.py``)
and the temperature module's ``HTTPException(410)`` is the only
public surface this file pins.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_router_app() -> FastAPI:
    """Build a fresh FastAPI app with only the temperature router
    mounted (no module registry). Keeps the surface small so each
    test exercises the tombstone in isolation.
    """
    from modules.temperature.router import router as temperature_router

    app = FastAPI()
    app.include_router(temperature_router, prefix="/api/v1/modules/temperature")
    return app



# ---------------------------------------------------------------------------
# Direct invocation — bypass the HTTP client to pin the behaviour
# ---------------------------------------------------------------------------


def test_set_target_direct_invocation_raises_410():
    """Driving the route function directly must raise ``HTTPException``
    with status code ``410`` — pinning the tombstone without going
    through the FastAPI test client keeps the contract surface tiny.
    """
    from fastapi import HTTPException

    from modules.temperature.router import set_target as set_target_fn

    with pytest.raises(HTTPException) as excinfo:
        set_target_fn(name="extruder", req=MagicMock(sensor_name="extruder", target=210.0))

    assert excinfo.value.status_code == 410