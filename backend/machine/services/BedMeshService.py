"""Bed mesh compensation on / off (`.agent/component/bed_mesh.md`).

``webgui.bed-mesh-enable`` is netted to ``compensation.enable-in`` in
``webgui_connections.hal`` (``BedMeshWebguiMapper``) on a machine with
``[bed_mesh]``. Switching it on (re)loads the active mesh and applies its
Z offset through the external offsets; off moves the offset back to 0.
The meshes themselves are files, kept by the system service.
"""
from __future__ import annotations

import logging
from typing import Optional

from dtos.pins.HalPin import HalDataType, HalPin
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin

logger = logging.getLogger("backend.services.bed_mesh")


class BedMeshService:
    def __init__(self) -> None:
        self._enable: Optional[HalPin[bool]] = None

    def preload_hal_pins(self) -> None:
        self._enable = ReadWriteDynamicHalPin(
            "bed-mesh-enable", HalDataType.BIT,
            "Bed mesh: Z compensation on (compensation.enable-in)",
        )

    def _pin(self) -> HalPin[bool]:
        if self._enable is None:
            logger.warning("Bed mesh pin used before preload! Forcing late initialization.")
            self.preload_hal_pins()
        assert self._enable is not None
        return self._enable

    def is_enabled(self) -> bool:
        return bool(self._pin().get_value())

    def set_enabled(self, enabled: bool) -> bool:
        self._pin().set_value(enabled)
        return self.is_enabled()


_service: Optional[BedMeshService] = None


def get_bed_mesh_service() -> BedMeshService:
    global _service
    if _service is None:
        _service = BedMeshService()
    return _service


__all__ = ["BedMeshService", "get_bed_mesh_service"]
