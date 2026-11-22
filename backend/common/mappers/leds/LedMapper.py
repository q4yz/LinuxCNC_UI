"""LED chains: pins from the profile, the state DTO, the response."""
from __future__ import annotations

from typing import Any, Dict

from core.led_color import decode
from dtos.leds.LedDto import LedPins, LedSegmentDTO, LedStateDTO
from dtos.pins.HalPin import HalDataType
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from models.LedModels import Led, LedSegment


class LedMapper:
    @staticmethod
    def from_dict_to_LedPins(led: Dict[str, Any]) -> LedPins:
        """A ``hardware.json`` ``leds`` entry; no ``segments``: one segment, the whole chain."""
        led_id = str(led["id"])
        chain = int(led.get("chain_count") or 1)
        segments = tuple((int(first), int(count)) for first, count in (led.get("segments") or [[1, chain]]))
        initial = (list(led.get("initial") or []) + [0.0] * 4)[:4]
        return LedPins(
            id=led_id,
            chain_count=chain,
            color_order=str(led.get("color_order") or "GRB"),
            segments=segments,
            pins=tuple(
                ReadWriteDynamicHalPin[float](f"led-{led_id}-{k}", HalDataType.FLOAT, f"LED {led_id} segment {k + 1}: 0xRRGGBB")
                for k in range(len(segments))
            ),
            initial=(float(initial[0]), float(initial[1]), float(initial[2]), float(initial[3])),
        )

    @staticmethod
    def to_state_dto(pins: LedPins) -> LedStateDTO:
        segments = []
        for (first, count), pin in zip(pins.segments, pins.pins):
            red, green, blue = decode(float(pin.get_value() or 0.0))
            segments.append(LedSegmentDTO(first, count, red, green, blue))
        return LedStateDTO(pins.id, pins.chain_count, pins.color_order, tuple(segments))

    @staticmethod
    def to_response(dto: LedStateDTO) -> Led:
        return Led(
            id=dto.id,
            chain_count=dto.chain_count,
            color_order=dto.color_order,
            segments=[LedSegment(first=s.first, count=s.count, red=s.red, green=s.green, blue=s.blue)
                      for s in dto.segments],
        )


__all__ = ["LedMapper"]
