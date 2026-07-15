"""Temperature module definition.

Implements the :class:`core.protocols.PluggableModule` contract for the
temperature feature. The module is intentionally small:

* ``on_load`` is a no-op — the simulation thread (when enabled) lives
  in the mock hardware layer and runs process-wide; this module only
  exposes the HTTP API.
* ``on_unload`` is idempotent (no-op).
* ``get_router`` returns the :data:`router` built by
  :mod:`backend.modules.temperature.router`.

Settings defaults are loaded eagerly so the registry can pass the
:class:`SettingsStore` a defaults model (see
``backend/core/module_registry.py``). Backend does not currently
*read* the settings — the four fields are consumed by the frontend
store, but we expose them through the canonical settings endpoints
so they can be tuned at runtime from the Settings UI.
"""

import logging
from typing import Optional

from fastapi import APIRouter

from core.protocols import (
    ModuleContext,
    ModuleManifest,
    PluggableModule,
)

from .router import router as _router
from .settings import TemperatureSettings

logger = logging.getLogger("backend.modules.temperature")


class TemperatureModule:
    """Module that exposes the temperature HTTP surface.

    The :attr:`manifest` is class-level so the registry can read it
    without instantiating the module. ``settings_panel=True`` causes
    the registry to render a Settings tab for this module. The
    :meth:`get_settings_model` hook returns a fresh
    :class:`TemperatureSettings` instance which the registry merges
    under the user's persisted settings on every read.
    """

    manifest = ModuleManifest(
        id="temperature",
        title="Temperature",
        version="0.1.0",
        description="Heater target / actual sensor monitoring.",
        settings_panel=True,
    )

    def on_load(self, ctx: ModuleContext) -> None:
        """Boot the temperature module.

        No background work is scheduled here — the mock's
        ``_temp_simulation_loop`` runs process-wide and is started on
        first ``set_temperature`` invocation. Future revisions may
        publish telemetry to the :class:`EventBus` from here; that is
        Phase 4 work.
        """
        logger.debug("temperature module on_load (no background work)")

    def on_unload(self) -> None:
        """Tear the module down.

        Idempotent: nothing to release because ``on_load`` does not
        allocate state.
        """
        logger.debug("temperature module on_unload (no-op)")

    def get_router(self) -> APIRouter:
        """Return the temperature HTTP router.

        The registry mounts this at
        ``/api/v1/modules/temperature`` with OpenAPI tag
        ``modules:temperature``.
        """
        return _router

    def get_settings_model(self) -> Optional[TemperatureSettings]:
        """Return a fresh :class:`TemperatureSettings` defaults model.

        The :class:`PluggableModule` protocol requires this method (it
        is part of the ``isinstance`` check) even though the registry
        tolerates ``None`` returns. Returning the defaults instance
        seeds the per-module :class:`SettingsStore` so the four
        canonical settings endpoints expose typed values instead of
        arbitrary JSON.
        """
        return TemperatureSettings()


def setup() -> PluggableModule:
    """Factory consumed by :class:`ModuleRegistry.discover`.

    Returning a fresh instance per call keeps state isolated between
    test runs and avoids leaking class-level state across reloads.
    """
    return TemperatureModule()


# Eagerly expose the settings defaults model so callers (and the
# registry, when extended) can import it without reaching into
# :mod:`.settings` directly. The class itself is the public API.
__all__ = ["TemperatureModule", "setup", "TemperatureSettings"]
