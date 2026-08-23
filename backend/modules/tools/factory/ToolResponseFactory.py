from typing import Union, Optional

from core.field_masking import ResponseTier
from modules.tools.mapper.SpindleDigitalMapper import SpindleDigitalMapper
from modules.tools.mapper.ExtruderMapper import ExtruderMapper
from modules.tools.mapper.HeaterMapper import HeaterMapper
from modules.tools.models.ExtruderModels import ExtruderStateResponse
from modules.tools.models.HeaterModels import HeaterStateResponse
from modules.tools.models.SpindleDigitalModels import SpindleDigitalStateResponse



ToolStateResponseModel = Union[
    SpindleDigitalStateResponse,
    HeaterStateResponse,
    ExtruderStateResponse
]


class ToolResponseFactory:
    """Translates internal Tool Domain DTOs into flattened HTTP Response models."""

    @staticmethod
    def create(state_dto, mode: ResponseTier = ResponseTier.ALL) -> Optional[ToolStateResponseModel]:
        """The master factory engine with mode projection."""

        # Note: Swap these to `isinstance(state_dto, YourDTOClass)` using your actual DTO classes
        type_name = state_dto.__class__.__name__

        if type_name == "SpindleDigitalStateDTO":
            return SpindleDigitalMapper.to_response(state_dto, mode)

        if type_name == "HeaterStateDTO":
            return HeaterMapper.to_response(state_dto, mode)

        if type_name == "ExtruderStateDTO":
            return ExtruderMapper.to_response(state_dto, mode)

        return None

    # --- Quality-of-Life Wrappers ---

    @staticmethod
    def create_base(state_dto) -> Optional[ToolStateResponseModel]:
        """Generates ONLY the 1Hz live dynamic fields for the tool."""
        return ToolResponseFactory.create(state_dto, ResponseTier.BASE)

    @staticmethod
    def create_static(state_dto) -> Optional[ToolStateResponseModel]:
        """Generates ONLY the static configuration fields for the tool."""
        return ToolResponseFactory.create(state_dto, ResponseTier.STATIC)