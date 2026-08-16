"""Temperature module definition.

Implements the :class:`core.protocols.PluggableModule` contract for the
temperature feature.

Following the Domain-Driven refactoring, active hardware telemetry and
dispatch logic has moved to the `tools` module and the `TemperatureService`.
This module now primarily serves to:

* Mount the legacy HTTP router tombstone (safely rejecting old client requests).
* Seed the `sensor_colors` settings so the frontend dashboard charts have a
  consistent palette for all heaters and standalone sensors.
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

# Import both standalone sensors and tools to ensure all are assigned colors
from .config_mapper import get_temperature_sensors
from modules.tools.config_mapper import get_all_heater

from .router import router as _router
from .settings import TemperatureSettings, seed_colors

logger = logging.getLogger("backend.modules.temperature")


class TemperatureModule:
    """Module that exposes the temperature HTTP surface and settings."""

    manifest = ModuleManifest(
        id="temperature",
        title="Temperature",
        version="0.1.0",
        description="Heater and standalone sensor settings.",
        # The temperature module has no sidebar entry — it lives
        # inside the dashboard grid rather than as a top-level nav
        # item. The manifest declares the entry explicitly anyway
        # because the contract forbids a None sidebar; the empty
        # ``id`` keeps it from being merged into the nav list.
        sidebar=SidebarEntry(id="", label="", icon="", order=100),
        settings_panel=True,
    )

    def __init__(self) -> None:
        # The active sensor list is captured at construction time
        # so the registry can seed the `sensor_colors` map for the SettingsStore.
        self._sensor_ids: List[str] = self._gather_all_sensor_ids()

    def _gather_all_sensor_ids(self) -> List[str]:
        """Gather all sensor IDs to seed their chart colors."""
        return [
            str(sensor["id"])
            for sensor in get_temperature_sensors()
            if sensor.get("id")
        ]

    def on_load(self, ctx: ModuleContext) -> None:
        """Boot the temperature module.

        Re-reads the active sensor list to pick up any in-process re-deployments.
        """
        self._sensor_ids = self._gather_all_sensor_ids()
        logger.debug(
            "temperature module on_load (sensors=%s)",
            self._sensor_ids,
        )

    def on_unload(self) -> None:
        """Tear the module down (idempotent)."""
        self._sensor_ids = []
        logger.debug("temperature module on_unload (no-op)")

    def get_router(self) -> APIRouter:
        """Return the deprecated temperature HTTP router tombstone."""
        return _router

    def get_settings_model(self) -> Optional[TemperatureSettings]:
        """Return a fresh :class:`TemperatureSettings` defaults model.

        Each call returns a **fresh** instance so the :class:`SettingsStore`
        merge semantics pick up the freshly-captured sensor list. The
        ``sensor_colors`` map is seeded from all active heaters and sensors.
        """
        return TemperatureSettings(sensor_colors=seed_colors(self._sensor_ids))


def setup() -> PluggableModule:
    """Factory consumed by :class:`ModuleRegistry.discover`."""
    return TemperatureModule()


__all__ = ["TemperatureModule", "setup", "TemperatureSettings"]