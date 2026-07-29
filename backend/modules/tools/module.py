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

The module intentionally does **not** expose a typed Pydantic
settings schema — the issue's hard-coded mock tool list will be
replaced by a dynamic config in a follow-up. Until then,
``get_settings_model`` returns ``None`` and the registry falls back
to untyped JSON for the canonical settings endpoints.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from core.protocols import (
    ModuleContext,
    ModuleManifest,
    PluggableModule,
)

from .router import router as _router

logger = logging.getLogger("backend.modules.tools")


_MANIFEST = ModuleManifest(
    id="tools",
    title="Tools",
    version="0.1.0",
    description=(
        "Spindle and extruder control via MDI commands "
        "(M3 / M4 / M5 for spindles, G91+G1+G90 for extruders)."
    ),
    # Tools live inside the dashboard grid, not as a top-level
    # nav item — matches the temperature module.
    sidebar=None,
    # No settings panel yet. The mock tool list is hard-coded in
    # the frontend store (see ``frontend/src/modules/tools/``)
    # until dynamic configuration lands.
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

    def get_settings_model(self) -> Optional[BaseModel]:
        """Return ``None`` until a typed settings schema exists.

        Issue #64 intentionally ships without a Pydantic defaults
        model — the dynamic tool configuration is a follow-up.
        Returning ``None`` lets the registry fall back to untyped
        JSON for the canonical settings endpoints.
        """
        return None


def setup() -> PluggableModule:
    """Factory consumed by :class:`ModuleRegistry.discover`.

    A fresh instance per ``setup()`` call keeps per-module state
    isolated between tests and avoids leaking class-level state
    across reloads.
    """
    return ToolsModule()


__all__ = ["ToolsModule", "setup"]