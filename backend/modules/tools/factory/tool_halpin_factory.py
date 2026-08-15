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
from typing import Any, Dict, Optional
from modules.tools.dtos import (
    ToolPins,
)
from modules.tools.mapper.analog_spindle_mapper import SpindleAnalogMapper
from modules.tools.mapper.digital_spindle_mapper import SpindleDigitalMapper
from modules.tools.mapper.extruder_mapper import ExtruderMapper
from modules.tools.mapper.heater_mapper import HeaterMapper


class ToolHalPinFactory:
    @staticmethod
    def create(data: Dict[str, Any]) -> Optional[ToolPins]:
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


__all__ = ["ToolHalPinFactory", "ToolPins"]
