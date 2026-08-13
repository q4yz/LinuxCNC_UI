"""Axis module — :class:`PluggableModule` implementation.

This file is the entrypoint the registry imports via the package
``setup()`` factory. It owns:

* the static :class:`ModuleManifest` describing the module,
* the per-module :class:`MachineSettings` defaults passed to the
  registry's :class:`SettingsStore`,
* the jog-watchdog lifecycle hooks :meth:`on_load` and
  :meth:`on_unload`.

Scope: this module owns the "axis" surface — jog control plus the
``/home`` endpoint. The ``/home`` endpoint is an axis-motion action
(similar in nature to jog dispatch), so it lives here rather than
in the ``state`` module. The state / mode / MDI endpoints live in
:mod:`backend.modules.state.router`; both routers call into the
shared layer-2 facade :class:`MachineControlService` from
:mod:`backend.services.machine_service`.

The HTTP router lives in :mod:`backend.modules.axis.router` and
currently exposes only ``POST /home``. Jog REST endpoints were
deprecated in favour of the ``/ws/telemetry`` channel; jog
WS-dispatch helpers live in :mod:`backend.modules.axis.jog`;
the watchdog background task in
:mod:`backend.modules.axis.jog_watchdog`. Settings schema in
:mod:`backend.modules.axis.settings`.

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
from .router import router as axis_router
from .settings import MachineSettings

logger = logging.getLogger("backend.modules.axis")


_MANIFEST = ModuleManifest(
    id="axis",
    title="Axis",
    version="0.1.0",
    description=(
        "Jog control + watchdog for axis motion, plus the /home "
        "endpoint. State / mode / MDI live in the machine_state module."
    ),
    # No sidebar entry — the machine dashboard lives at the root,
    # mounted by ``App.vue`` rather than as a top-level nav item.
    sidebar=None,
    settings_panel=True,
)


class AxisModule:
    """The :class:`PluggableModule` instance the registry boots.

    The module owns the jog-watchdog background task in
    :mod:`backend.modules.axis.jog_watchdog`. The watchdog needs the
    module-private ``_active_jogs`` map that lives with the jog
    helpers in :mod:`backend.modules.axis.jog`, so we keep both in
    the same package.

    The router exposes only ``POST /home`` today — jog REST
    endpoints were deprecated in favour of the ``/ws/telemetry``
    channel and the state / mode / MDI endpoints live in
    :mod:`backend.modules.state.router`. ``get_router`` returns
    the ``APIRouter`` so the registry can mount it under
    ``/api/v1/modules/axis``.
    """

    manifest = _MANIFEST

    def __init__(self) -> None:
        # Axis module's HTTP router. Currently exposes ``POST /home``;
        # jog REST endpoints were deprecated. The router itself lives
        # in :mod:`backend.modules.axis.router`.
        self._router: APIRouter = axis_router

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
        logger.info("Axis module loaded.")

    def on_unload(self) -> None:
        """Cancel the watchdog and clear module-private state.

        Idempotent under ``uvicorn --reload`` — calling
        :func:`stop_watchdog` more than once is safe; the registry
        may invoke this hook multiple times during a reload cycle.
        """
        try:
            jog_watchdog.stop_watchdog()
        except Exception as exc:  # noqa: BLE001 - defensive
            logger.error("AxisModule.on_unload: stop_watchdog raised %s", exc)
        logger.info("Axis module unloaded.")

    # ------------------------------------------------------------------ #
    # Registry hooks                                                     #
    # ------------------------------------------------------------------ #

    def get_router(self) -> APIRouter:
        """Return the axis module's HTTP router.

        The router exposes ``POST /home``; jog REST endpoints were
        deprecated in favour of the ``/ws/telemetry`` channel.
        The registry mounts the router at
        ``/api/v1/modules/axis`` with OpenAPI tag ``modules:axis``.
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
    return AxisModule()


__all__ = ["AxisModule", "setup", "MachineSettings"]