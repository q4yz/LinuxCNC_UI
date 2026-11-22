"""Z tilt: the motor offset pins, the state DTO, the response."""
from __future__ import annotations

from typing import Optional

from dtos.pins.HalPin import HalDataType
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from dtos.z_tilt.ZTiltDto import ZTiltPins, ZTiltStateDTO
from models.ZTiltModels import ZTiltStatus


class ZTiltMapper:
    @staticmethod
    def create_ZTiltPins(motors: int) -> ZTiltPins:
        return ZTiltPins(offsets=tuple(
            ReadWriteDynamicHalPin[float](f"ztilt-{k}", HalDataType.FLOAT, f"Z tilt: motor {k} offset (mm)")
            for k in range(motors)
        ))

    @staticmethod
    def offsets(pins: ZTiltPins) -> tuple[float, ...]:
        return tuple(float(pin.get_value() or 0.0) for pin in pins.offsets)

    @staticmethod
    def to_state_dto(configured: bool, running: bool, pins: ZTiltPins, spread: Optional[float]) -> ZTiltStateDTO:
        return ZTiltStateDTO(configured=configured, running=running, offsets=ZTiltMapper.offsets(pins), spread=spread)

    @staticmethod
    def to_response(dto: ZTiltStateDTO) -> ZTiltStatus:
        return ZTiltStatus(configured=dto.configured, running=dto.running, offsets=list(dto.offsets), spread=dto.spread)


__all__ = ["ZTiltMapper"]
