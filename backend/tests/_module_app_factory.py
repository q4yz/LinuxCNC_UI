"""Test helper: build a FastAPI app with one (or more) per-domain routers.

Replaces the legacy ``ModuleRegistry.boot(candidates=[...])`` fixture so
test files can keep their endpoint assertions verbatim while the
backend's boot path lives in :mod:`backend.main`.

Usage:

    def test_foo(tmp_data_root, clean_env):
        app = build_module_app("axis", tmp_data_root)
        client = TestClient(app)
        resp = client.post("/api/v1/modules/axis/home", json={"axis": -1})
        assert resp.status_code == 200

The helper:

* Constructs a :class:`SettingsStore` for the requested module id and
  mounts the canonical four-endpoint settings router under
  ``/api/v1/modules/<id>/settings``.
* Mounts the module's HTTP router under ``/api/v1/modules/<id>``.
* Optionally mounts additional routers (the legacy flat routers, e.g.
  ``FilesRouter``) so tests that exercise cross-router flows keep
  working.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from fastapi import FastAPI

from core.settings_store import SettingsStore
from routers._module_settings_router import (
    build_module_settings_router,
)

# Settings-model registry: maps module id to the Pydantic defaults
# class. The settings class is instantiated once per app and passed
# to :class:`SettingsStore` as ``defaults=`` so a fresh checkout
# returns a non-empty payload.
_MODULE_SETTINGS_MODELS: dict[str, type] = {}


def _ensure_settings_registry() -> None:
    """Lazy-load the eight per-module settings models.

    Importing them at module load would force every test to spin up
    pydantic + hardware mocks; the lazy lookup keeps the helper
    light when a test only needs the router.
    """
    if _MODULE_SETTINGS_MODELS:
        return
    from models.axis_settings import MachineSettings
    from models.camera_settings import CameraSettings
    from models.machineconfig_settings import MachineConfigSettings
    from models.macros_settings import MacrosSettings
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
            "macros": MacrosSettings,
            "camera": CameraSettings,
            "machineconfig": MachineConfigSettings,
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
        "macros": "routers.macros",
        "camera": "routers.camera",
        "machineconfig": "routers.machineconfig",
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
    extra_routers: Optional[Iterable] = None,
    settings_model=None,
) -> FastAPI:
    """Build a FastAPI app that mounts one module's routers + settings.

    Args:
        module_id: One of the eight canonical module ids.
        data_root: Per-test settings persistence root (usually the
            ``tmp_data_root`` pytest fixture).
        extra_routers: Optional iterable of additional routers to
            mount (e.g. ``[BaseThreadRouter.router]``). Mounted in the
            order supplied, *after* the module's settings router and
            router so the module's paths take precedence.
        settings_model: Override the default settings class for this
            module. Defaults to the canonical ``models.<id>_settings``
            Pydantic class. Tests that need a custom defaults model
            (e.g. an empty BaseModel) can pass their own.
    """
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
