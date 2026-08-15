"""Tool State factory.

Single dispatch table that maps a typed HAL pin record into
the evaluated operator-facing state DTO:

* SpindleDigitalPins → SpindleDigitalStateDTO
* SpindleAnalogPins  → SpindleAnalogStateDTO
* ExtruderPins       → ExtruderStateDTO
* HeaterPins         → HeaterStateDTO

The factory is the single place that decides which State DTO a pin
record turns into, ensuring consumers can blindly pass any valid 
ToolPins object and receive the correct telemetry snapshot.
"""

from __future__ import annotations

from typing import Optional, Union

# Import the Pin classes (Inputs)
from modules.tools.dtos import (
    ExtruderPins,
    HeaterPins,
    SpindleAnalogPins,
    SpindleDigitalPins,
    ToolPins, ToolStateDTO,
)



# Import the Mappers
from modules.tools.mapper.analog_spindle_mapper import SpindleAnalogMapper
from modules.tools.mapper.digital_spindle_mapper import SpindleDigitalMapper
from modules.tools.mapper.extruder_mapper import ExtruderMapper
from modules.tools.mapper.heater_mapper import HeaterMapper

# Define the Union for the return type


class ToolStateFactory:

    @staticmethod
    def create(pins: ToolPins) -> Optional[ToolStateDTO]:

        if isinstance(pins, SpindleDigitalPins):
            return SpindleDigitalMapper.to_state_dto(pins)

        if isinstance(pins, SpindleAnalogPins):
            return SpindleAnalogMapper.to_state_dto(pins)

        if isinstance(pins, ExtruderPins):
            return ExtruderMapper.to_state_dto(pins)

        if isinstance(pins, HeaterPins):
            return HeaterMapper.to_state_dto(pins)

        return None

__all__ = ["ToolStateFactory", "ToolStateDTO"]