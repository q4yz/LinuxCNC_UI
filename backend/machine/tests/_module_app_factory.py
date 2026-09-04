"""Test helper: build a FastAPI app with one machine-backend module router.

Machine-app variant of the shared factory: the registry only knows
the machine-owned module ids (``axis``, ``machine_state``,
``program``, ``temperature``, ``tools``, ``camera``) plus the
``macros`` execution router (``POST /{name}/start`` — mounted
without a settings store because the macros settings are owned by
the system service).

Usage:

    def test_foo(tmp_data_root, clean_env):
        app = build_module_app("axis", tmp_data_root)
        client = TestClient(app)
        resp = client.post("/api/v1/modules/axis/home", json={"axis": -1})
        assert resp.status_code == 200
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from fastapi import APIRouter, FastAPI

from core.settings_store import SettingsStore
from module_settings_router import build_module_settings_router

# Settings-model registry: maps module id to the Pydantic defaults
# class. ``None`` means the module has no machine-side settings
# surface (its settings store lives in the other service).
_MODULE_SETTINGS_MODELS: dict[str, Optional[type]] = {}


def _ensure_settings_registry() -> None:
    """Lazy-load the machine-owned settings models."""
    if _MODULE_SETTINGS_MODELS:
        return
    from models.axis_settings import MachineSettings
    from models.camera_settings import CameraSettings
    from models.program_settings import ProgramSettings
    from models.state_settings import StateSettings
    from models.temperature_settings import TemperatureSettings
    from models.tools_settings import ToolsSettings

    _MODULE_SETTINGS_MODELS.update(
        {
            "axis": MachineSettings,
            "machine_state": StateSettings,
            "program": ProgramSettings,
            "temperature": TemperatureSettings,
            "tools": ToolsSettings,
            "camera": CameraSettings,
            "macros": None,  # settings owned by the system service
        }
    )


def _resolve_router(module_id: str):
    """Return the per-domain :class:`fastapi.APIRouter` for ``module_id``."""
    mapping = {
        "axis": "routers.axis",
        "machine_state": "routers.state",
        "program": "routers.program",
        "temperature": "routers.temperature",
        "tools": "routers.tools",
        "camera": "routers.camera",
        "macros": "routers.macro_start",
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
    """Build a FastAPI app that mounts one module's routers + settings.

    The canonical settings router is only mounted when the module
    owns a settings model on this side (or an explicit
    ``settings_model`` override is supplied).
    """
    _ensure_settings_registry()

    app = FastAPI()
    settings_cls = settings_model or _MODULE_SETTINGS_MODELS.get(module_id)
    if settings_cls is not None:
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
