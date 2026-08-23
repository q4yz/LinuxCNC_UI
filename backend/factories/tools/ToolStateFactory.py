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
from dtos.tools import (
    ExtruderPins,
    HeaterPins,
    SpindleAnalogPins,
    SpindleDigitalPins,
    ToolPins, ToolStateDTO,
)



# Import the Mappers
from mappers.tools.SpindleAnalogMapper import SpindleAnalogMapper
from mappers.tools.SpindleDigitalMapper import SpindleDigitalMapper
from mappers.tools.ExtruderMapper import ExtruderMapper
from mappers.tools.HeaterMapper import HeaterMapper

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