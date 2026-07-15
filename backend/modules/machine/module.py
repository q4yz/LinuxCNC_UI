"""Machine module — :class:`PluggableModule` implementation.

This file is the entrypoint the registry imports via the package
``setup()`` factory. It owns:

* the static :class:`ModuleManifest` describing the module,
* the per-module :class:`MachineSettings` defaults passed to the
  registry's :class:`SettingsStore`,
* the lifecycle hooks :meth:`on_load` and :meth:`on_unload`,
* the start/stop of the 500 ms jog safety watchdog.

The actual HTTP routers live in :mod:`backend.modules.machine.router`
and :mod:`backend.modules.machine.jog`; settings schema in
:mod:`backend.modules.machine.settings`; the watchdog in
:mod:`backend.modules.machine.jog_watchdog`.

The watchdog is started in :meth:`on_load` rather than at import
time so the registry can wire the per-module :class:`SettingsStore`
in first (the watchdog reads the configured timeout via that store).
The shutdown side mirrors the start: :meth:`on_unload` cancels the
task and clears :data:`jog._active_jogs` so the next boot starts
clean.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter

from core.protocols import (
    ModuleContext,
    ModuleManifest,
    PluggableModule,
)

from . import jog_watchdog
from .jog import router as jog_router
from .router import router as machine_router
from .settings import MachineSettings

logger = logging.getLogger("backend.modules.machine")


_MANIFEST = ModuleManifest(
    id="machine",
    title="Machine",
    version="0.1.0",
    description="DRO, jogging, state, MDI, home.",
    # No sidebar entry — the machine dashboard lives at the root,
    # mounted by ``App.vue`` rather than as a top-level nav item.
    sidebar=None,
    settings_panel=True,
)


class MachineModule:
    """The :class:`PluggableModule` instance the registry boots.

    The module owns three routers (state/mode/home/mdi in
    :mod:`backend.modules.machine.router`; jog/keepalive/stop in
    :mod:`backend.modules.machine.jog`) plus one long-lived
    background task — the 500 ms keep-alive watchdog in
    :mod:`backend.modules.machine.jog_watchdog`. The watchdog needs
    the module-private ``_active_jogs`` map that lives with the
    router, so we keep both in the same package.

    Concatenating the two routers into one :class:`APIRouter` at
    mount time would also work, but the two files stay split so
    future readers can grep ``POST /jog`` / ``POST /state``
    independently. The registry only sees one router though —
    ``get_router`` returns the merged instance.
    """

    manifest = _MANIFEST

    def __init__(self) -> None:
        # Merge the two module-level routers into one so the
        # registry can mount a single ``APIRouter`` under
        # ``/api/v1/modules/machine``. ``include_router`` keeps all
        # operation ids and tags intact.
        merged = APIRouter(tags=["modules:machine"])
        merged.include_router(machine_router)
        merged.include_router(jog_router)
        self._router: APIRouter = merged

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def on_load(self, ctx: ModuleContext) -> None:
        """Start the watchdog.

        The watchdog reads its timeout from :data:`ctx.settings`, so
        this method intentionally runs *after* the registry has
        constructed the per-module :class:`SettingsStore`. All
        other work (router mounting, manifest registration) is done
        by the registry before this hook fires.

        Starting the watchdog is non-blocking — it schedules an
        asyncio task on the running loop. The task idles until the
        first continuous jog is registered.
        """
        jog_watchdog.start_watchdog(ctx.settings)
        logger.info("Machine module loaded.")

    def on_unload(self) -> None:
        """Cancel the watchdog and clear module-private state.

        Idempotent under ``uvicorn --reload`` — calling
        :func:`stop_watchdog` more than once is safe; the registry
        may invoke this hook multiple times during a reload cycle.
        """
        try:
            jog_watchdog.stop_watchdog()
        except Exception as exc:  # noqa: BLE001 - defensive
            logger.error("MachineModule.on_unload: stop_watchdog raised %s", exc)
        logger.info("Machine module unloaded.")

    # ------------------------------------------------------------------ #
    # Registry hooks                                                     #
    # ------------------------------------------------------------------ #

    def get_router(self) -> APIRouter:
        """Return the merged machine HTTP router.

        The router exposes both the state/mode/home/mdi endpoints
        (from :mod:`backend.modules.machine.router`) and the
        jog/keepalive/stop endpoints (from
        :mod:`backend.modules.machine.jog`). The registry mounts it
        at ``/api/v1/modules/machine`` with OpenAPI tag
        ``modules:machine``.
        """
        return self._router

    def get_settings_model(self) -> Optional[MachineSettings]:
        """Return a fresh :class:`MachineSettings` defaults model.

        The registry passes this to :class:`SettingsStore` as the
        ``defaults`` argument. Returning ``None`` falls back to
        untyped JSON, which we explicitly avoid so the documented
        settings keys are validated on every PUT.
        """
        return MachineSettings()


def setup() -> PluggableModule:
    """Factory consumed by :class:`ModuleRegistry.discover`.

    A fresh instance per ``setup()`` call keeps per-module state
    isolated between tests and avoids leaking class-level state
    across reloads.
    """
    return MachineModule()


__all__ = ["MachineModule", "setup", "MachineSettings"]
