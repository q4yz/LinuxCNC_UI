from typing import Optional, Union

from modules.temperature.dtos.temperature_dto import SensorPin, SensorStateDto
from modules.temperature.mapper.temperature_mapper import TemperatureSensorMapper
# Adjust these imports based on your actual project structure
from modules.tools.dtos.heater_dto import HeaterPins, HeaterStateDTO
from modules.tools.mapper.heater_mapper import HeaterMapper



# Type aliases for clean hinting
TemperaturePins = Union[HeaterPins, SensorPin]
TemperatureStateDTO = Union[HeaterStateDTO, SensorStateDto]


class TemperatureStateFactory:
    """Factory to translate hardware pins into runtime state DTOs for the temperature module."""

    @staticmethod
    def create(pins: TemperaturePins) -> Optional[TemperatureStateDTO]:

        if isinstance(pins, HeaterPins):
            return HeaterMapper.to_state_dto(pins)

        if isinstance(pins, SensorPin):
            return TemperatureSensorMapper.to_state_dto(pins)

        return None


__all__ = ["TemperatureStateFactory", "TemperaturePins", "TemperatureStateDTO"]