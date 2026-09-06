from typing import Dict, Any, TYPE_CHECKING

from core.field_masking import ResponseTier, include_base, include_static
from dtos.pins.HalPin import  HalDataType
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from dtos.pins.StaticHalPin import StaticHalPin
from dtos.pins.UnconnectedHalPin import UnconnectedHalPin
from dtos.tools.HeaterDto import HeaterStateDTO, HeaterPins, HeaterSettingsDTO
from mappers.tools.OptionalMappers import OptionalMappers
from models.tools.HeaterModels import HeaterStateResponse

if TYPE_CHECKING:
    from routers.tools import HeaterCommand


class HeaterMapper:

    @classmethod
    def from_dict_to_HeaterPins(cls, data: Dict[str, Any]) -> HeaterPins:
        tool_id = str(data["id"])
        suffix = tool_id.replace("heater", "")
        fan_val = data.get("fan")

        return HeaterPins(
            id=tool_id,
            target_temperature=ReadWriteDynamicHalPin(f"target-temperature{suffix}", HalDataType.FLOAT, ""),
            actual_temperature=ReadWriteDynamicHalPin(f"actual-temperature{suffix}", HalDataType.FLOAT, ""),
            fan=ReadWriteDynamicHalPin(str(fan_val), HalDataType.FLOAT, "") if fan_val else UnconnectedHalPin(),
            min_temp=StaticHalPin(OptionalMappers.as_optional_number(data.get("min_temp"), float) or 0.0),
            max_temp=StaticHalPin(OptionalMappers.as_optional_number(data.get("max_temp"), float) or 300.0),
        )

    @classmethod
    def to_state_dto(cls, halpin: HeaterPins) -> HeaterStateDTO:
        return HeaterStateDTO(
            id=halpin.id,
            target_temperature=OptionalMappers.as_float(halpin.target_temperature.get_value()),
            actual_temperature=OptionalMappers.as_float(halpin.actual_temperature.get_value()),
            fan=OptionalMappers.as_float(halpin.fan.get_value()),
            min_temp=OptionalMappers.as_float(halpin.min_temp.get_value()),
            max_temp=OptionalMappers.as_float(halpin.max_temp.get_value()),
        )

    @classmethod
    def from_command_to_settings_dto(cls, cmd: "HeaterCommand") -> HeaterSettingsDTO:
        """Translates the HTTP heater command into the internal domain DTO."""
        return HeaterSettingsDTO(
            id=cmd.id,
            target_temperature=cmd.target,
            enable=(cmd.target > 0.0)
        )

    @classmethod
    def to_response(cls, dto: HeaterStateDTO, r : ResponseTier = ResponseTier.ALL) -> HeaterStateResponse:
        return HeaterStateResponse(
            id=dto.id,
            target= include_base(dto.target_temperature, r),
            actual=include_base(dto.actual_temperature, r),
            min_temp=include_static( dto.min_temp, r),
            max_temp=include_static( dto.max_temp, r)
        )

