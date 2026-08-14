"""State module — :class:`PluggableModule` implementation.

This file is the entrypoint the registry imports via the package
``setup()`` factory. It owns:

* the static :class:`ModuleManifest` describing the module,
* no-op :meth:`on_load` and :meth:`on_unload` lifecycle hooks (the
  state module has no background work, watchdog, or hardware
  handles to manage).

Scope is narrow: this module is the HTTP surface for machine state,
mode, and MDI. The business logic lives in
:mod:`modules.state.service` (the :class:`StateService` facade);
this module is a thin wrapper that delegates to the facade's
singleton.

The HTTP router lives in :mod:`backend.modules.state.router`. The
business facade (:class:`StateService`) lives in
:mod:`modules.state.service`. The ``/home`` endpoint intentionally
lives in the axis module because homing is an axis-motion action;
everything else (state / mode / MDI) lives here.

The state module declares a typed settings surface via
:mod:`backend.modules.state.settings` so the canonical four
endpoints expose a non-empty payload from first boot.
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

from .router import router as state_router
from .settings import StateSettings

logger = logging.getLogger("backend.modules.state")


_MANIFEST = ModuleManifest(
    id="machine_state",
    title="Machine State",
    version="0.1.0",
    description=(
        "Read/set machine state, mode, and MDI. "
        "Home lives in the axis module."
    ),
    # The state module has no sidebar entry — the machine dashboard
    # is mounted at the root by ``App.vue``. The manifest declares
    # the entry explicitly anyway because the contract forbids a
    # None sidebar; the empty ``id`` keeps it from being merged into
    # the nav list.
    sidebar=SidebarEntry(id="", label="", icon="", order=100),
    # No settings panel — the state module has no user-tunable
    # settings today. The typed defaults schema in
    # :mod:`backend.modules.state.settings` keeps the canonical
    # four endpoints non-empty without rendering a Settings tab.
    settings_panel=False,
)


class StateModule:
    """The :class:`PluggableModule` instance the registry boots.

    The module is a pure HTTP surface — no watchdog, no event-bus
    subscriptions, no background tasks. ``on_load`` and
    ``on_unload`` are no-ops kept for protocol symmetry with
    :class:`backend.modules.axis.AxisModule`.

The router exposes ``GET /state``, ``POST /state``, ``POST /mode``,
and ``POST /mdi``; the ``/home`` endpoint lives in the axis
module. Both routers call into the shared :class:`StateService`
singleton in :mod:`modules.state.service` (and the axis module
into :class:`AxisService` in :mod:`modules.axis.service`).
    """

    manifest = _MANIFEST

    def __init__(self) -> None:
        self._router: APIRouter = state_router

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def on_load(self, ctx: ModuleContext) -> None:
        """No-op — the state module has nothing to bootstrap.

        Kept for protocol symmetry with :class:`AxisModule` so the
        registry's boot path can call it uniformly. The router is
        already constructed in :meth:`__init__` and is mounted by
        the registry after this hook returns.
        """
        logger.info("State module loaded.")

    def on_unload(self) -> None:
        """No-op — symmetric with :meth:`on_load`.

        Idempotent under ``uvicorn --reload`` — calling this more
        than once is safe because there is no state to release.
        """
        logger.info("State module unloaded.")

    # ------------------------------------------------------------------ #
    # Registry hooks                                                     #
    # ------------------------------------------------------------------ #

    def get_router(self) -> APIRouter:
        """Return the state module's HTTP router.

        The registry mounts it at ``/api/v1/modules/machine_state``
        with OpenAPI tag ``modules:machine_state``.
        """
        return self._router

    def get_settings_model(self) -> BaseModel:
        """Return a fresh :class:`StateSettings` defaults instance.

        The contract requires a non-null :class:`BaseModel`. See
        :mod:`backend.modules.state.settings` for the schema.
        """
        return StateSettings()


def setup() -> PluggableModule:
    """Factory consumed by :class:`ModuleRegistry.discover`.

    A fresh instance per ``setup()`` call keeps per-module state
    isolated between tests and avoids leaking class-level state
    across reloads.
    """
    return StateModule()


__all__ = ["StateModule", "setup", "StateSettings"]