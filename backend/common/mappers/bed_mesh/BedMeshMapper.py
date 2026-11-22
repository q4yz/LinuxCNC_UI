"""Bed mesh compensation on / off: the pin, the state DTO, the response."""
from __future__ import annotations

from dtos.bed_mesh.BedMeshDto import BedMeshPins, BedMeshStateDTO
from dtos.pins.HalPin import HalDataType
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from models.BedMeshModels import BedMeshEnable


class BedMeshMapper:
    @staticmethod
    def create_BedMeshPins() -> BedMeshPins:
        return BedMeshPins(enable=ReadWriteDynamicHalPin(
            "bed-mesh-enable", HalDataType.BIT, "Bed mesh: Z compensation on (compensation.enable-in)"))

    @staticmethod
    def to_state_dto(pins: BedMeshPins) -> BedMeshStateDTO:
        return BedMeshStateDTO(enabled=bool(pins.enable.get_value()))

    @staticmethod
    def to_response(dto: BedMeshStateDTO) -> BedMeshEnable:
        return BedMeshEnable(enabled=dto.enabled)


__all__ = ["BedMeshMapper"]
