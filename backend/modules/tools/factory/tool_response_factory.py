from typing import Union, Optional

from modules.tools.mapper.digital_spindle_mapper import SpindleDigitalMapper
from modules.tools.mapper.extruder_mapper import ExtruderMapper
from modules.tools.mapper.heater_mapper import HeaterMapper
from modules.tools.models.extruder_models import ExtruderStateResponse
from modules.tools.models.heater_models import HeaterStateResponse
from modules.tools.models.spindel_digital_models import SpindleDigitalStateResponse

# Import your Domain DTOs
# from modules.tools.dtos import SpindleDigitalStateDTO, HeaterStateDTO, ExtruderStateDTO

ToolStateResponseModel = Union[
    SpindleDigitalStateResponse,
    HeaterStateResponse,
    ExtruderStateResponse
]


class ToolResponseFactory:
    """Translates internal Tool Domain DTOs into flattened HTTP Response models."""

    @staticmethod
    def create(state_dto) -> Optional[ToolStateResponseModel]:
        # Note: Swap these to `isinstance(state_dto, YourDTOClass)` using your actual DTO classes

        type_name = state_dto.__class__.__name__

        if type_name == "SpindleDigitalStateDTO":
            return SpindleDigitalMapper.to_response(state_dto)

        if type_name == "HeaterStateDTO":
            return HeaterMapper.to_response(state_dto)

        if type_name == "ExtruderStateDTO":
            return ExtruderMapper.to_response(state_dto)

        return None