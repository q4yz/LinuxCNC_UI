from typing import Union, Optional

from core.field_masking import ResponseTier
from modules.temperature.models.TemperatureResponse import TemperatureStateResponse
# Adjust these imports to match your project's exact structure
from modules.tools.dtos import HeaterStateDTO
from modules.temperature.dtos.SensorDto import SensorStateDto
from modules.tools.mapper.HeaterMapper import HeaterMapper
from modules.temperature.mapper.TemperatureSensorMapper import TemperatureSensorMapper
from modules.tools.models.HeaterModels import HeaterStateResponse

# Type aliases for clean hinting
TemperatureStateDTO = Union[HeaterStateDTO, SensorStateDto]
TemperatureResponseModel = Union[HeaterStateResponse, TemperatureStateResponse]


class TemperatureResponseFactory:
    """Factory to translate internal temperature state DTOs into HTTP Response models."""

    @staticmethod
    def create(state: TemperatureStateDTO ,r : ResponseTier = ResponseTier.ALL) -> Optional[TemperatureResponseModel]:

        if isinstance(state, HeaterStateDTO):
            return HeaterMapper.to_response(state, r)

        if isinstance(state, SensorStateDto):
            return TemperatureSensorMapper.to_response(state, r)

        return None


__all__ = ["TemperatureResponseFactory", "TemperatureStateDTO", "TemperatureResponseModel"]