"""Test helper: build a FastAPI app with one system-service module router.

System-app variant of the shared factory: knows the system-owned
module ids (``machineconfig``, ``macros``). UI settings have their own
router (``routers.ui_settings``) and tests.

Usage:

    def test_foo(tmp_data_root, clean_env):
        app = build_module_app("macros", tmp_data_root)
        client = TestClient(app)
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Iterable, Optional

from fastapi import APIRouter, FastAPI

_ROUTERS = {
    "machineconfig": "routers.machineconfig",
    "macros": "routers.macros",
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

    ``data_root`` is accepted for call-site compatibility.
    """
    app = FastAPI()
    app.include_router(_resolve_router(module_id))
    for router in extra_routers or ():
        app.include_router(router)
    return app


__all__ = ["build_module_app"]
