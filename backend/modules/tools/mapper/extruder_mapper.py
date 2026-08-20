from typing import Dict, Any, TYPE_CHECKING

from dtos.HalPin import ReadWriteDynamicHalPin, HalDataType
from modules.tools.dtos.extruder_dto import ExtruderPins, ExtruderStateDTO, ExtruderSettingsDTO
from modules.tools.dtos.heater_dto import HeaterSettingsDTO

from modules.tools.mapper.heater_mapper import HeaterMapper  # Adjust import path
from modules.tools.mapper.as_optional_mappers import OptionalMappers
from modules.tools.models.extruder_models import ExtruderStateResponse

if TYPE_CHECKING:
    from modules.tools.router import ExtruderCommand


class ExtruderMapper:

    @classmethod
    def from_dict_to_ExtruderPins(cls, data: Dict[str, Any]) -> ExtruderPins:
        tool_id = str(data["id"])

        position_val = data.get("position", f"{tool_id}_position")

        return ExtruderPins(
            id=tool_id,
            heater=HeaterMapper.from_dict_to_HeaterPins(data),
            position=ReadWriteDynamicHalPin(str(position_val), HalDataType.FLOAT),
        )

    @classmethod
    def to_state_dto(cls, halpin: ExtruderPins) -> ExtruderStateDTO:
        return ExtruderStateDTO(
            id=halpin.id,
            heater=HeaterMapper.to_state_dto(halpin.heater),
            position=OptionalMappers.as_float(halpin.position.get_value()),
        )

    @classmethod
    def from_command_to_settings_dto( cls,cmd: "ExtruderCommand") -> ExtruderSettingsDTO:

        distance = cmd.distance if cmd.action.lower() == "extrude" else -cmd.distance

        # ``heater_action`` controls whether the heater gets
        # dispatched at all. ``"set"`` keeps the legacy behaviour
        # (the move also asserts the heater target). ``"noop"``
        # leaves the heater alone so an extrude/retract does not
        # implicitly toggle the heater back on. The field is
        # non-nullable so a misconfigured caller is caught by
        # Pydantic validation before the service layer runs.
        heater_dto = (
            HeaterMapper.from_command_to_settings_dto(cmd.heater)
            if cmd.heater_action == "set"
            else None
        )

        return ExtruderSettingsDTO(
            id=cmd.tool_id,
            heater=heater_dto,
            relative_distance=distance,
            speed=cmd.speed,
        )

    @classmethod
    def to_response(cls, dto) -> ExtruderStateResponse:
        return ExtruderStateResponse(
            id=dto.id,
            heater=HeaterMapper.to_response(dto.heater),
            position=getattr(dto, "position", 0.0)
        )