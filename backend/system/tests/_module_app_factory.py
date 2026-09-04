"""Test helper: build a FastAPI app with one system-service module router.

System-app variant of the shared factory: the registry only knows
the system-owned module ids (``machineconfig``, ``macros`` — the
file-CRUD half; the ``POST /{name}/start`` execution endpoint lives
in the machine backend).
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from fastapi import APIRouter, FastAPI

from core.settings_store import SettingsStore
from module_settings_router import build_module_settings_router

_MODULE_SETTINGS_MODELS: dict[str, type] = {}


def _ensure_settings_registry() -> None:
    """Lazy-load the system-owned settings models."""
    if _MODULE_SETTINGS_MODELS:
        return
    from models.machineconfig_settings import MachineConfigSettings
    from models.macros_settings import MacrosSettings

    _MODULE_SETTINGS_MODELS.update(
        {
            "machineconfig": MachineConfigSettings,
            "macros": MacrosSettings,
        }
    )


def _resolve_router(module_id: str):
    """Return the per-domain :class:`fastapi.APIRouter` for ``module_id``."""
    mapping = {
        "machineconfig": "routers.machineconfig",
        "macros": "routers.macros",
    }
    if module_id not in mapping:
        raise KeyError(f"unknown module id: {module_id!r}")
    import importlib

    mod = importlib.import_module(mapping[module_id])
    return mod.router


def build_module_app(
    module_id: str,
    data_root: Path,
    *,
    extra_routers: Optional[Iterable[APIRouter]] = None,
    settings_model=None,
) -> FastAPI:
    """Build a FastAPI app that mounts one module's routers + settings."""
    _ensure_settings_registry()

    app = FastAPI()
    settings_cls = settings_model or _MODULE_SETTINGS_MODELS[module_id]
    store = SettingsStore(
        module_id=module_id,
        data_root=data_root,
        defaults=settings_cls(),
    )
    app.include_router(
        build_module_settings_router(store),
        prefix=f"/api/v1/modules/{module_id}/settings",
        tags=[f"modules:{module_id}:settings"],
    )
    app.include_router(_resolve_router(module_id))
    if extra_routers:
        for router in extra_routers:
            app.include_router(router)
    return app


__all__ = ["build_module_app"]
