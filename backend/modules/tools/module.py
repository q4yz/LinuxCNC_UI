"""Tools module — :class:`PluggableModule` implementation.

This file is the entrypoint the registry imports via the package-level
``setup()`` factory. It owns:

* the static :class:`ModuleManifest` describing the module,
* the lifecycle hooks :meth:`on_load` and :meth:`on_unload`,
* the router reference returned by :meth:`get_router`.

The actual HTTP router lives in :mod:`backend.modules.tools.router`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from core.protocols import (
    ModuleContext,
    ModuleManifest,
    PluggableModule,
    SidebarEntry,
)

from .router import router as _router
from .settings import ToolsSettings

logger = logging.getLogger("backend.modules.tools")


_MANIFEST = ModuleManifest(
    id="tools",
    title="Tools",
    version="0.2.0",
    description=(
        "Operator-facing tool control: spindle (M3 / M4 / M5), "
        "extruder (G91 + G1 + G90), and per-tool target temperature "
        "via the canonical hardware.json ``tools[]`` list."
    ),
    sidebar=SidebarEntry(
        id="tools",
        label="Tools",
        icon="",
        order=90,
    ),
    settings_panel=False,
)


class ToolsModule:
    """The :class:`PluggableModule` instance the registry boots."""

    manifest = _MANIFEST

    def __init__(self) -> None:
        # Share the module-level router with the registry.
        self._router: APIRouter = _router

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def on_load(self, ctx: ModuleContext) -> None:
        """Boot the tools module.

        HAL pin initialization and queueing is now handled globally
        by ToolsService and HalPin during the FastAPI lifespan.
        """
        logger.info("Tools module loaded.")

    def on_unload(self) -> None:
        """Tear the tools module down."""
        logger.debug("Tools module unloaded.")

    # ------------------------------------------------------------------ #
    # Registry hooks                                                     #
    # ------------------------------------------------------------------ #

    def get_router(self) -> APIRouter:
        """Return the module's HTTP router."""
        return self._router

    def get_settings_model(self) -> BaseModel:
        """Return a fresh :class:`ToolsSettings` defaults instance."""
        return ToolsSettings()


def setup() -> PluggableModule:
    """Factory consumed by :class:`ModuleRegistry.discover`."""
    return ToolsModule()


__all__ = ["ToolsModule", "setup", "ToolsSettings"]