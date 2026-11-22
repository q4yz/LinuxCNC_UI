"""Tool HAL pin factory.

Single dispatch table that maps a raw ``hardware.json`` tool record
into the right concrete pin record:

* ``spindle_digital`` → :class:`SpindleDigitalPins`
* ``spindle_analog``  → :class:`SpindleAnalogPins`
* ``extruder`` / ``heated_bed`` → :class:`HeaterPins`

The factory is the single place that decides which DTO a tool
record turns into; every consumer (:class:`ToolsService`,
:func:`get_spindle_hal_pin_maps`) goes through it so a future tool
type only needs one branch added here.
"""

from __future__ import annotations
from typing import Any, Dict, Optional, Type, TypeVar, Union
from dtos.tools import (
    ExtruderPins,
    HeaterPins,
    SpindleAnalogPins,
    SpindleDigitalPins,
    ToolPins,
)

T = TypeVar("T")
AnyToolPin = Union[ExtruderPins, HeaterPins, SpindleAnalogPins, SpindleDigitalPins]
from mappers.tools.SpindleAnalogMapper import SpindleAnalogMapper
from mappers.tools.SpindleDigitalMapper import SpindleDigitalMapper
from mappers.tools.ExtruderMapper import ExtruderMapper
from mappers.tools.HeaterMapper import HeaterMapper


class ToolPinsMapper:
    @staticmethod
    def from_dict_to_ToolPins(data: Dict[str, Any]) -> Optional[ToolPins]:
        tool_type = data.get("type")
        tool_id = data.get("id")

        if not isinstance(tool_type, str) or not isinstance(tool_id, str) or not tool_id:
            return None

        if tool_type == "spindle_digital":
            return SpindleDigitalMapper.from_dict_to_SpindleDigitalPins(data)

        if tool_type == "spindle_analog":
            return SpindleAnalogMapper.from_dict_to_SpindleAnalogPins(data)

        if tool_type == "extruder":
            return ExtruderMapper.from_dict_to_ExtruderPins(data)

        if tool_type == "heated_bed":
            return HeaterMapper.from_dict_to_HeaterPins(data)

        return None

    @staticmethod
    def of_type(data: AnyToolPin, expected_type: Type[T]) -> Optional[T]:

        if expected_type is ExtruderPins:
            if isinstance(data, ExtruderPins):
                return data

        if expected_type is HeaterPins:
            if isinstance(data, ExtruderPins):
                return data.heater
            if isinstance(data, HeaterPins):
                return data

        if expected_type is SpindleDigitalPins:
            if isinstance(data, SpindleDigitalPins):
                return data

        if expected_type is SpindleAnalogPins:
            if isinstance(data, SpindleAnalogPins):
                return data

        return None


__all__ = ["AnyToolPin", "ToolPinsMapper", "ToolPins"]
