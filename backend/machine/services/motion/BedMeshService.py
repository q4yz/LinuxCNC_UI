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

from dtos.bed_mesh.BedMeshDto import BedMeshPins, BedMeshStateDTO
from mappers.bed_mesh.BedMeshMapper import BedMeshMapper
from services.HalPinService import HalPinService

logger = logging.getLogger("backend.services.bed_mesh")


class BedMeshService(HalPinService):
    def __init__(self) -> None:
        self._pins: Optional[BedMeshPins] = None

    def preload_hal_pins(self) -> None:
        self._pins = BedMeshMapper.create_BedMeshPins()

    def _bed_mesh_pins(self) -> BedMeshPins:
        if self._pins is None:
            logger.warning("Bed mesh pin used before preload! Forcing late initialization.")
            self.preload_hal_pins()
        assert self._pins is not None
        return self._pins

    def state(self) -> BedMeshStateDTO:
        return BedMeshMapper.to_state_dto(self._bed_mesh_pins())

    def is_enabled(self) -> bool:
        return self.state().enabled

    def set_enabled(self, enabled: bool) -> bool:
        self._bed_mesh_pins().enable.set_value(enabled)
        return self.is_enabled()


_service: Optional[BedMeshService] = None


def get_bed_mesh_service() -> BedMeshService:
    global _service
    if _service is None:
        _service = BedMeshService()
    return _service


__all__ = ["BedMeshService", "get_bed_mesh_service"]
