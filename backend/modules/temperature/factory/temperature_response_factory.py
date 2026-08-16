from typing import Union, Optional

from modules.temperature.models.temperature_models import TemperatureStateResponse
# Adjust these imports to match your project's exact structure
from modules.tools.dtos import HeaterStateDTO
from modules.temperature.dtos.temperature_dto import SensorStateDto
from modules.tools.mapper.heater_mapper import HeaterMapper
from modules.temperature.mapper.temperature_mapper import TemperatureSensorMapper
from modules.tools.models.heater_models import HeaterStateResponse

# Type aliases for clean hinting
TemperatureStateDTO = Union[HeaterStateDTO, SensorStateDto]
TemperatureResponseModel = Union[HeaterStateResponse, TemperatureStateResponse]


class TemperatureResponseFactory:
    """Factory to translate internal temperature state DTOs into HTTP Response models."""

    @staticmethod
    def create(state: TemperatureStateDTO) -> Optional[TemperatureResponseModel]:

        if isinstance(state, HeaterStateDTO):
            return HeaterMapper.to_response(state)

        if isinstance(state, SensorStateDto):
            return TemperatureSensorMapper.to_response(state)

        return None


__all__ = ["TemperatureResponseFactory", "TemperatureStateDTO", "TemperatureResponseModel"]