"""State module — :class:`PluggableModule` implementation.

This file is the entrypoint the registry imports via the package
``setup()`` factory. It owns:

* the static :class:`ModuleManifest` describing the module,
* no-op :meth:`on_load` and :meth:`on_unload` lifecycle hooks (the
  state module has no background work, watchdog, or hardware
  handles to manage).

Scope is narrow: this module is the HTTP surface for machine state,
mode, and MDI. The business logic lives in
:mod:`backend.services.machine_service` (the
``MachineControlService`` facade); this module is a thin wrapper
that delegates to the facade's singleton.

The HTTP router lives in :mod:`backend.modules.state.router`. The
``/home`` endpoint intentionally lives in the axis module because
homing is an axis-motion action; everything else (state / mode /
MDI) lives here.

The state module has no user-tunable settings today, so
:meth:`get_settings_model` returns ``None`` and the registry skips
the canonical four-endpoint settings router for this module.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from core.protocols import (
    ModuleContext,
    ModuleManifest,
    PluggableModule,
)

from .router import router as state_router

logger = logging.getLogger("backend.modules.state")


_MANIFEST = ModuleManifest(
    id="machine_state",
    title="Machine State",
    version="0.1.0",
    description=(
        "Read/set machine state, mode, and MDI. "
        "Home lives in the axis module."
    ),
    # No sidebar entry — the machine dashboard lives at the root,
    # mounted by ``App.vue`` rather than as a top-level nav item.
    sidebar=None,
    # No settings panel — the state module has no user-tunable
    # settings today. Adding one later is a single-line flip here
    # plus a Pydantic defaults model in a sibling ``settings.py``.
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
    module. Both routers call into the shared
    :class:`MachineControlService` singleton in
    :mod:`backend.services.machine_service`.
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

    def get_settings_model(self):
        """Return ``None`` — the state module has no settings today.

        The registry reads this via :func:`getattr` and tolerates
        ``AttributeError`` / ``None`` so opting out is a single
        ``None`` return. When a future settings schema lands,
        replace with a Pydantic ``BaseModel`` subclass.
        """
        return None


def setup() -> PluggableModule:
    """Factory consumed by :class:`ModuleRegistry.discover`.

    A fresh instance per ``setup()`` call keeps per-module state
    isolated between tests and avoids leaking class-level state
    across reloads.
    """
    return StateModule()


__all__ = ["StateModule", "setup"]