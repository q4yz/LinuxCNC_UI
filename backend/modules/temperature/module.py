"""Temperature module definition.

Implements the :class:`core.protocols.PluggableModule` contract for the
temperature feature. The module is intentionally small:

* ``on_load`` reads the active heater list from
  ``machine_config/active/hardware.json`` so the seeded
  ``sensor_colors`` map matches what the operator's machine.cfg
  actually declared. The helper lives in
  :mod:`backend.modules.temperature.hardware_loader` so the mock
  and the settings seed always agree.
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
from typing import List, Optional

from fastapi import APIRouter

from core.protocols import (
    ModuleContext,
    ModuleManifest,
    PluggableModule,
    SidebarEntry,
)
from .config_mapper import load_active_heaters

from .router import router as _router
from .settings import TemperatureSettings, seed_colors

logger = logging.getLogger("backend.modules.temperature")


class TemperatureModule:
    """Module that exposes the temperature HTTP surface.

    The :attr:`manifest` is class-level so the registry can read it
    without instantiating the module. ``settings_panel=True`` causes
    the registry to render a Settings tab for this module. The
    :meth:`get_settings_model` hook returns a fresh
    :class:`TemperatureSettings` instance — the
    :func:`modules.temperature.hardware_loader.load_active_heaters`
    helper seeds the ``sensor_colors`` map so a freshly deployed
    machine starts with the canonical colour palette for every
    heater the operator declared.
    """

    manifest = ModuleManifest(
        id="temperature",
        title="Temperature",
        version="0.1.0",
        description="Heater target / actual sensor monitoring.",
        # The temperature module has no sidebar entry — it lives
        # inside the dashboard grid rather than as a top-level nav
        # item. The manifest declares the entry explicitly anyway
        # because the contract forbids a None sidebar; the empty
        # ``id`` keeps it from being merged into the nav list.
        sidebar=SidebarEntry(id="", label="", icon="", order=100),
        settings_panel=True,
    )

    def __init__(self) -> None:
        # The active heater list is captured at construction time
        # (called via ``setup()`` during registry discovery). The
        # registry invokes :meth:`get_settings_model` *before*
        # :meth:`on_load`, so we must populate this list at
        # ``__init__`` — not inside ``on_load`` — for the seeded
        # ``sensor_colors`` to flow through to ``SettingsStore``.
        # The list is cached on the instance for the lifetime of
        # the module; ``on_load`` re-reads it to pick up any
        # in-process re-deployment (rare in practice — most operators
        # restart the backend between deploys).
        self._heater_names: List[str] = load_active_heaters()

    def on_load(self, ctx: ModuleContext) -> None:
        """Boot the temperature module.

        Re-reads the active heater list and caches it on the
        instance. The mock's ``_temp_simulation_loop`` runs
        process-wide and is started on first ``set_temperature``
        invocation — this method does **not** spawn background work.
        """
        self._heater_names = load_active_heaters()
        logger.debug(
            "temperature module on_load (heaters=%s)",
            self._heater_names,
        )

    def on_unload(self) -> None:
        """Tear the module down.

        Idempotent: nothing to release because ``on_load`` does not
        allocate state.
        """
        self._heater_names = []
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

        Each call returns a **fresh** instance so the
        :class:`SettingsStore` merge semantics pick up the
        freshly-captured heater list — see issue #97 acceptance
        criteria. The ``sensor_colors`` map is seeded from the
        active heater list via :func:`seed_colors`.
        """
        return TemperatureSettings(sensor_colors=seed_colors(self._heater_names))


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