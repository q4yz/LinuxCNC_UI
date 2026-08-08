"""Pluggable module for custom macro file storage."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from core.protocols import ModuleContext, ModuleManifest, PluggableModule

from .router import create_router
from .service import MacroFileService
from .settings import MACROS_STORAGE_DIR


class MacrosModule:
    """Lifecycle owner for the macro CRUD service and router."""

    manifest = ModuleManifest(
        id="macros",
        title="Macros",
        settings_panel=False,
    )

    def __init__(self) -> None:
        self._service = MacroFileService(MACROS_STORAGE_DIR)
        self._router = create_router(self._service)

    def on_load(self, ctx: ModuleContext) -> None:
        """Create the configured storage directory when the module loads."""
        self._service.storage_dir.mkdir(parents=True, exist_ok=True)

    def on_unload(self) -> None:
        """Unload the module; it owns no resources requiring cleanup."""

    def get_router(self) -> Optional[APIRouter]:
        """Return the macro CRUD router."""
        return self._router

    def get_settings_model(self) -> Optional[BaseModel]:
        """Macros currently have no typed, operator-editable settings."""
        return None


def setup() -> PluggableModule:
    """Return a fresh macros module for registry discovery."""
    return MacrosModule()


__all__ = ["MacrosModule", "setup"]
