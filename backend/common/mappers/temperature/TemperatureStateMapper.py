from typing import Optional, Union

from dtos.sensors.TemperatureDto import TemperaturePin
from mappers.temperature.TemperatureResponseMapper import TemperatureStateDTO
from mappers.temperature.TemperatureSensorMapper import TemperatureSensorMapper
# Adjust these imports based on your actual project structure
from dtos.tools.HeaterDto import HeaterPins, HeaterStateDTO
from mappers.tools.HeaterMapper import HeaterMapper



# Type aliases for clean hinting
TemperaturePins = Union[HeaterPins, TemperaturePin]
AllTemperatureStateDTO = Union[HeaterStateDTO, TemperatureStateDTO]


class TemperatureStateMapper:
    """Pins -> state DTO for the temperature module (heater or plain sensor)."""

    @staticmethod
    def to_state_dto(pins: TemperaturePins) -> Optional[AllTemperatureStateDTO]:

        if isinstance(pins, HeaterPins):
            return HeaterMapper.to_state_dto(pins)

        if isinstance(pins, TemperaturePin):
            return TemperatureSensorMapper.to_state_dto(pins)

        return None


__all__ = ["TemperatureStateMapper", "TemperaturePins", "TemperatureStateDTO"]