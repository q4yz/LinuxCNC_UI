"""Test helper: build a FastAPI app with one machine-backend module router.

Machine-app variant of the shared factory: knows the machine-owned
module ids (``axis``, ``machine_state``, ``program``, ``temperature``,
``tools``, ``camera``) plus the ``macros`` execution router
(``POST /{name}/start``). UI settings are not served by the machine
backend (they live in the system service's ``/api/v1/settings``).

Usage:

    def test_foo(tmp_data_root, clean_env):
        app = build_module_app("axis", tmp_data_root)
        client = TestClient(app)
        resp = client.post("/api/v1/modules/axis/home", json={"axis": -1})
        assert resp.status_code == 200
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Iterable, Optional

from fastapi import APIRouter, FastAPI

from exceptions import register_command_error_handler

_ROUTERS = {
    "axis": "routers.axis",
    "machine_state": "routers.state",
    "program": "routers.program",
    "temperature": "routers.temperature",
    "tools": "routers.tools",
    "camera": "routers.camera",
    "macros": "routers.macro_start",
}


def _resolve_router(module_id: str) -> APIRouter:
    if module_id not in _ROUTERS:
        raise KeyError(f"unknown module id: {module_id!r}")
    return importlib.import_module(_ROUTERS[module_id]).router


def build_module_app(
    module_id: str,
    data_root: Optional[Path] = None,
    *,
    extra_routers: Optional[Iterable[APIRouter]] = None,
) -> FastAPI:
    """Build a FastAPI app that mounts one module's router.

    ``data_root`` is accepted for call-site compatibility; nothing on
    the machine side persists settings any more.
    """
    app = FastAPI()
    register_command_error_handler(app)  # same as machine/main.py
    app.include_router(_resolve_router(module_id))
    for router in extra_routers or ():
        app.include_router(router)
    return app


__all__ = ["build_module_app"]
