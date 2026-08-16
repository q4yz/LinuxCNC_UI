from typing import Dict, Any, TYPE_CHECKING

from dtos.HalPin import DynamicHalPin, StaticHalPin, UnconnectedHalPin
from modules.tools.dtos.heater_dto import HeaterStateDTO, HeaterPins, HeaterSettingsDTO
from modules.tools.mapper.as_optional_mappers import OptionalMappers
from modules.tools.models.heater_models import HeaterStateResponse

if TYPE_CHECKING:
    from modules.tools.router import HeaterCommand, HeaterCommandStateResponse


class HeaterMapper:

    @classmethod
    def from_dict_to_HeaterPins(cls, data: Dict[str, Any]) -> HeaterPins:
        tool_id = str(data["id"])
        suffix = tool_id.replace("heater", "")

        fan_val = data.get("fan")

        return HeaterPins(
            id=tool_id,
            target_temperature=DynamicHalPin(f"target-temperature{suffix}"),
            actual_temperature=DynamicHalPin(f"actual-temperature{suffix}"),
            fan=DynamicHalPin(str(fan_val)) if fan_val else UnconnectedHalPin(),
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
            id=cmd.tool_id,
            target_temperature=cmd.target,
            enable=(cmd.target > 0.0)
        )

    @classmethod
    def to_response(cls, dto: HeaterStateDTO) -> HeaterStateResponse:
        return HeaterStateResponse(
            tool_id=dto.id,
            target=dto.target_temperature,
            actual=dto.actual_temperature,
            min_temp=dto.min_temp,
            max_temp=dto.max_temp,
        )

