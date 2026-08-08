"""Macros module — :class:`PluggableModule` implementation.

This file is the entrypoint the registry imports via the package-level
``setup()`` factory. It owns:

* the static :class:`ModuleManifest` describing the module,
* the lifecycle hooks :meth:`on_load` and :meth:`on_unload`,
* the router reference returned by :meth:`get_router`.

The actual HTTP router lives in :mod:`backend.modules.macros.router`;
the actual filesystem storage lives in
:mod:`backend.modules.macros.storage`. This file is intentionally
thin: every filesystem concern is delegated so the module class
itself has no I/O to perform in ``on_load`` and can stay
non-blocking (see :file:`.agent/contracts/backend-module.md` § 5).

The module intentionally does **not** expose a typed Pydantic
settings schema — there are no settings for a pure CRUD module. The
registry mounts the canonical four settings endpoints anyway, but
they will always return ``{}`` because the module has no defaults
model.
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

logger = logging.getLogger("backend.modules.macros")


# ---------------------------------------------------------------------- #
# Manifest                                                                #
# ---------------------------------------------------------------------- #


_MANIFEST = ModuleManifest(
    id="macros",
    title="Macros",
    version="0.1.0",
    description=(
        "CRUD over user-defined ``.macro`` files (raw text payloads "
        "eventually executed as a mix of G-code + Python). The "
        "frontend Activation list and Editor views land in a "
        "follow-up ticket; this module only owns storage and the "
        "HTTP surface."
    ),
    # Frontend will declare its own nav entry when the Activation
    # view lands — keep the manifest free of sidebar metadata for now.
    sidebar=None,
    # No settings panel today; the canonical settings endpoints are
    # mounted by the registry and will return an empty payload.
    settings_panel=False,
)


# ---------------------------------------------------------------------- #
# Module                                                                  #
# ---------------------------------------------------------------------- #


class MacrosModule:
    """The :class:`PluggableModule` instance the registry boots.

    Lifecycle is intentionally trivial: ``on_load`` is a no-op (no
    background workers, no event-bus subscriptions) and ``on_unload``
    only emits an info log so registry reloads show a clean teardown.
    The router's module-level storage singleton is constructed lazily
    on first request, so the module constructor itself does no I/O.
    """

    manifest = _MANIFEST

    def __init__(self) -> None:
        # Share the module-level router with the registry. The
        # registry mounts it under ``/api/v1/modules/macros``.
        self._router: APIRouter = _router

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def on_load(self, ctx: ModuleContext) -> None:
        """Boot the macros module.

        No background work is scheduled: every macro interaction is
        a single HTTP request that completes before the response is
        returned. We log the module id so operators can correlate
        registry summary lines with this module's mount order.
        """
        logger.debug(
            "macros module on_load (module_id=%s, no background work)",
            ctx.module_id,
        )

    def on_unload(self) -> None:
        """Tear the macros module down.

        Idempotent — nothing was allocated in :meth:`on_load`, so
        the registry can safely call this method more than once
        during ``uvicorn --reload`` cycles.
        """
        logger.debug("macros module on_unload (no-op)")

    # ------------------------------------------------------------------ #
    # Registry hooks                                                     #
    # ------------------------------------------------------------------ #

    def get_router(self) -> APIRouter:
        """Return the module's HTTP router.

        The registry mounts this at ``/api/v1/modules/macros`` with
        OpenAPI tag ``modules:macros``. Settings endpoints are
        mounted separately by the registry — see
        :meth:`ModuleRegistry._build_default_settings_router`.
        """
        return self._router

    def get_settings_model(self) -> Optional[BaseModel]:
        """Return ``None``; macros has no typed settings schema.

        The registry falls back to untyped JSON for the canonical
        settings endpoints, which return an empty ``{}`` for this
        module today.
        """
        return None


# ---------------------------------------------------------------------- #
# Factory                                                                 #
# ---------------------------------------------------------------------- #


def setup() -> PluggableModule:
    """Factory consumed by :class:`ModuleRegistry.discover`.

    A fresh instance per ``setup()`` call keeps per-module state
    isolated between tests and avoids leaking class-level state
    across reloads.
    """
    return MacrosModule()


__all__ = ["MacrosModule", "setup"]
