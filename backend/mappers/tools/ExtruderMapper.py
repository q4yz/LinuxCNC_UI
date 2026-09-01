from typing import Dict, Any, TYPE_CHECKING

from core.field_masking import ResponseTier, include_base
from dtos.pins.HalPin import  HalDataType
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from dtos.tools.ExtruderDto import ExtruderPins, ExtruderStateDTO, ExtruderSettingsDTO


from mappers.tools.HeaterMapper import HeaterMapper
from mappers.tools.OptionalMappers import OptionalMappers
from models.tools.ExtruderModels import ExtruderStateResponse

if TYPE_CHECKING:
    from routers.tools import ExtruderCommand


class ExtruderMapper:

    @classmethod
    def from_dict_to_ExtruderPins(cls, data: Dict[str, Any]) -> ExtruderPins:
        tool_id = str(data["id"])

        position_val = data.get("position", f"{tool_id}_position")

        return ExtruderPins(
            id=tool_id,
            heater=HeaterMapper.from_dict_to_HeaterPins(data),
            position=ReadWriteDynamicHalPin(str(position_val), HalDataType.FLOAT, ""),
        )

    @classmethod
    def to_state_dto(cls, halpin: ExtruderPins) -> ExtruderStateDTO:
        return ExtruderStateDTO(
            id=halpin.id,
            heater=HeaterMapper.to_state_dto(halpin.heater),
            position=OptionalMappers.as_float(halpin.position.get_value()),
        )

    @classmethod
    def from_command_to_settings_dto( cls,cmd: "ExtruderCommand", ) -> ExtruderSettingsDTO:

        distance = cmd.distance if cmd.action.lower() == "extrude" else -cmd.distance

        heater_dto = None

        if cmd.heater_action == "set":
            heater_dto = (HeaterMapper.from_command_to_settings_dto(cmd.heater))

        return ExtruderSettingsDTO(
            id=cmd.tool_id,
            heater=heater_dto,
            relative_distance=distance,
            speed=cmd.speed,
        )

    @classmethod
    def to_response(cls, dto, r : ResponseTier = ResponseTier.ALL) -> ExtruderStateResponse:
        return ExtruderStateResponse(
            id=dto.id,
            heater=HeaterMapper.to_response(dto.heater, r),
            position=include_base(getattr(dto, "position", 0.0), r)
        )