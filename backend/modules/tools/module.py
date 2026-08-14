"""Tools module — :class:`PluggableModule` implementation.

This file is the entrypoint the registry imports via the package-level
``setup()`` factory. It owns:

* the static :class:`ModuleManifest` describing the module,
* the lifecycle hooks :meth:`on_load` and :meth:`on_unload`,
* the router reference returned by :meth:`get_router`.

The actual HTTP router lives in :mod:`backend.modules.tools.router`;
no background work is scheduled today because all spindle /
extruder interactions are operator-initiated and complete in a
single request (Issue #64).

The module exposes a typed Pydantic settings schema via
:mod:`backend.modules.tools.settings`. The schema is intentionally
small so the canonical four settings endpoints expose a non-empty
payload from first boot; new knobs land as new keys on
:class:`ToolsSettings` without breaking the contract.
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
    version="0.1.0",
    description=(
        "Operator-facing tool control: spindle (M3 / M4 / M5), "
        "extruder (G91 + G1 + G90), and per-tool target temperature "
        "via the canonical hardware.json ``tools[]`` list."
    ),
    # Tools live inside the dashboard grid, not as a top-level
    # nav item — matches the temperature module. The manifest
    # declares the sidebar entry explicitly because the contract
    # forbids a None sidebar.
    sidebar=SidebarEntry(
        id="tools",
        label="Tools",
        icon="",
        order=90,
    ),
    # Settings panel stays off until the Settings UI gains a tab
    # for this module.
    settings_panel=False,
)


class ToolsModule:
    """The :class:`PluggableModule` instance the registry boots.

    Lifecycle is intentionally trivial today: ``on_load`` is a
    no-op (no background workers, no event-bus subscriptions) and
    ``on_unload`` only emits an info log so registry reloads show
    a clean teardown.
    """

    manifest = _MANIFEST

    def __init__(self) -> None:
        # Share the module-level router with the registry. The
        # registry mounts it under ``/api/v1/modules/tools``.
        self._router: APIRouter = _router

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def on_load(self, ctx: ModuleContext) -> None:
        """Boot the tools module.

        No background work is scheduled: every spindle / extruder
        interaction is a single HTTP request that completes before
        the response is returned. The mock tool list is owned by
        the frontend store, not the backend, so we don't need any
        pub/sub wiring here either.
        """
        logger.debug("tools module on_load (no background work)")

    def on_unload(self) -> None:
        """Tear the tools module down.

        Idempotent — nothing was allocated in :meth:`on_load`, so
        the registry can safely call this method more than once
        during ``uvicorn --reload`` cycles.
        """
        logger.debug("tools module on_unload (no-op)")

    # ------------------------------------------------------------------ #
    # Registry hooks                                                     #
    # ------------------------------------------------------------------ #

    def get_router(self) -> APIRouter:
        """Return the module's HTTP router.

        The registry mounts this at ``/api/v1/modules/tools`` with
        OpenAPI tag ``modules:tools``. Settings endpoints are
        mounted separately by the registry — see
        :meth:`ModuleRegistry._build_default_settings_router`.
        """
        return self._router

    def get_settings_model(self) -> BaseModel:
        """Return a fresh :class:`ToolsSettings` defaults instance.

        The contract requires a non-null :class:`BaseModel`. See
        :mod:`backend.modules.tools.settings` for the schema.
        """
        return ToolsSettings()


def setup() -> PluggableModule:
    """Factory consumed by :class:`ModuleRegistry.discover`.

    A fresh instance per ``setup()`` call keeps per-module state
    isolated between test runs and avoids leaking class-level state
    across reloads.
    """
    return ToolsModule()


__all__ = ["ToolsModule", "setup", "ToolsSettings"]