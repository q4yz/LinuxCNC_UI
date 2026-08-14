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

The module exposes a typed Pydantic settings schema via
:mod:`backend.modules.macros.settings`. The schema is intentionally
small — a single toggle for the dashboard's "dangerous macros"
visibility — but the contract forbids a ``None`` returns from
``get_settings_model()``.
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
from .settings import MacrosSettings

logger = logging.getLogger("backend.modules.macros")


# ---------------------------------------------------------------------- #
# Manifest                                                                #
# ---------------------------------------------------------------------- #


_MANIFEST = ModuleManifest(
    id="macros",
    title="Macros",
    version="0.2.0",
    description=(
        "CRUD over three kinds of operator-authored machine files: "
        "``.macro`` (custom G-code + python-block payloads), "
        "``.ngc`` (LinuxCNC native subroutines, toggled by the user), "
        "and bare ``M<num>`` files (LinuxCNC custom M-codes M100..M199 "
        "dispatched by the interpreter via ``USER_M_PATH``). The "
        "``.macro`` + ``.ngc`` halves share ``<repo>/macros/``; the "
        "M-code half uses ``<repo>/machine_config/m_codes/`` so the "
        "universal editor's profile mode picks them up the same way "
        "it picks up ``.cfg`` / ``.ini`` config files."
    ),
    # The macros module has no top-level sidebar entry — the
    # dashboard panel + Machine Config section cover both UIs.
    # The manifest declares the entry explicitly anyway because the
    # contract forbids a None sidebar; the empty ``id`` keeps it
    # from being merged into the nav list.
    sidebar=SidebarEntry(id="", label="", icon="", order=100),
    # The settings endpoints are mounted by the registry and expose
    # the typed payload from :class:`MacrosSettings`. ``settings_panel``
    # stays ``False`` because the Settings UI does not yet render a
    # macros tab; flip to ``True`` when the frontend gains one.
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

    def get_settings_model(self) -> BaseModel:
        """Return a fresh :class:`MacrosSettings` defaults instance.

        The contract requires a non-null :class:`BaseModel`. See
        :mod:`backend.modules.macros.settings` for the schema.
        """
        return MacrosSettings()


# ---------------------------------------------------------------------- #
# Factory                                                                 #
# ---------------------------------------------------------------------- #


def setup() -> PluggableModule:
    """Factory consumed by :class:`ModuleRegistry.discover`.

    A fresh instance per ``setup()`` call keeps per-module state
    isolated between test runs and avoids leaking class-level state
    across reloads.
    """
    return MacrosModule()


__all__ = ["MacrosModule", "setup", "MacrosSettings"]
