from typing import Union, Optional

from core.field_masking import ResponseTier
from dtos.sensors.TemperatureDto import TemperatureStateDto
from models.TemperatureStateResponse import TemperatureStateResponse
# Adjust these imports to match your project's exact structure
from dtos.tools import HeaterStateDTO

from mappers.tools.HeaterMapper import HeaterMapper
from mappers.temperature.TemperatureSensorMapper import TemperatureSensorMapper
from models.tools.HeaterModels import HeaterStateResponse

# Type aliases for clean hinting
TemperatureStateDTO = Union[HeaterStateDTO, TemperatureStateDto]
TemperatureResponseModel = Union[HeaterStateResponse, TemperatureStateResponse]


class TemperatureResponseMapper:
    """State DTO -> response model for the temperature module."""

    @staticmethod
    def to_response(state: TemperatureStateDTO ,r : ResponseTier = ResponseTier.ALL) -> Optional[TemperatureResponseModel]:

        if isinstance(state, HeaterStateDTO):
            return HeaterMapper.to_response(state, r)

        if isinstance(state, TemperatureStateDto):
            return TemperatureSensorMapper.to_response(state, r)

        return None


__all__ = ["TemperatureResponseMapper", "TemperatureStateDTO", "TemperatureResponseModel"]