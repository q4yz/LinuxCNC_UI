from typing import Dict, Any, TYPE_CHECKING

from dtos.HalPin import DynamicHalPin, StaticHalPin
from modules.tools.dtos import SpindleDigitalPins, SpindleDigitalStateDTO
from modules.tools.dtos.digital_spindle_dto import DirectionStateType, SpindleDigitalSettingsDTO
from modules.tools.mapper.as_optional_mappers import OptionalMappers
if TYPE_CHECKING:
    from modules.tools.router import SpindleDigitalCommand, SpindleDigitalStateResponse


class SpindleDigitalMapper():

    @classmethod
    def from_dict_to_SpindleDigitalPins(cls, data: Dict[str, Any]) -> SpindleDigitalPins:
        tool_id = str(data["id"])
        suffix = tool_id.replace("spindle_digital", "")

        return SpindleDigitalPins(
            id=tool_id,
            spindle_at_speed=DynamicHalPin(f"spindle-at-speed{suffix}"),
            target_rpm=DynamicHalPin(f"TargetRpm{suffix}"),
            actual_rpm=DynamicHalPin(f"rpm-out{suffix}"),
            is_connected=DynamicHalPin(f"is-connected{suffix}"),
            error_count=DynamicHalPin(f"error-count{suffix}"),
            last_error=DynamicHalPin(f"last-error{suffix}"),
            min_rpm=StaticHalPin(OptionalMappers.as_optional_number(data.get("min_rpm"), int) or 0),
            max_rpm=StaticHalPin(OptionalMappers.as_optional_number(data.get("max_rpm"), int) or 24000),
            spindle_forward=DynamicHalPin(f"spindle-forward{suffix}"),
            spindle_reverse=DynamicHalPin(f"spindle-reverse{suffix}"),
            override=DynamicHalPin(f"override{suffix}"),
        )

    @classmethod
    def to_state_dto(cls, halpin: SpindleDigitalPins) -> SpindleDigitalStateDTO:
        return SpindleDigitalStateDTO(
            id=halpin.id,
            target_rpm=OptionalMappers.as_float(halpin.target_rpm.get_value()),
            actual_rpm=OptionalMappers.as_float(halpin.actual_rpm.get_value()),
            is_connected=OptionalMappers.as_bool(halpin.is_connected.get_value()),
            error_count=OptionalMappers.as_int(halpin.error_count.get_value()),
            last_error=OptionalMappers.as_str(halpin.last_error.get_value()),
            spindle_at_speed=OptionalMappers.as_bool(halpin.spindle_at_speed.get_value()),
            min_rpm=OptionalMappers.as_float(halpin.min_rpm.get_value()),
            max_rpm=OptionalMappers.as_float(halpin.max_rpm.get_value()),
            spindle_forward=OptionalMappers.as_bool(halpin.spindle_forward.get_value()),
            spindle_reverse=OptionalMappers.as_bool(halpin.spindle_reverse.get_value()),
            override=OptionalMappers.as_bool(halpin.override.get_value()),
        )

    @classmethod
    def from_command_to_settings_dto(cls, cmd: "SpindleDigitalCommand") -> SpindleDigitalSettingsDTO:
        """Translates the HTTP command payload into the strict internal domain DTO."""

        # Safely map the string action to the Domain Enum
        action_map = {
            "forward": DirectionStateType.FORWARD,
            "backward": DirectionStateType.BACKWARD,
            "stop": DirectionStateType.IDLE,
        }

        # Fallback to IDLE just in case, though Pydantic validation
        # in the router should prevent invalid strings from reaching here.
        mapped_state = action_map.get(cmd.action.lower(), DirectionStateType.IDLE)

        return SpindleDigitalSettingsDTO(
            id=cmd.tool_id,
            speed=cmd.speed,
            master_override=cmd.master_override,
            override=cmd.override,
            master_override_enable=cmd.master_override_enable,
            state=mapped_state
        )

    @classmethod
    def to_response(cls, dto: SpindleDigitalStateDTO) -> "SpindleDigitalStateResponse":
        """Translates the internal State DTO to the HTTP Response Model."""

        # Consolidate hardware booleans into the UI string
        if dto.spindle_forward:
            state_str = "forward"
        elif dto.spindle_reverse:
            state_str = "backward"
        else:
            state_str = "idle"

        return SpindleDigitalStateResponse(
            id=dto.id,
            target_rpm=dto.target_rpm,
            actual_rpm=dto.actual_rpm,
            is_connected=dto.is_connected,
            error_count=dto.error_count,
            last_error=dto.last_error,
            spindle_at_speed=dto.spindle_at_speed,
            min_rpm=dto.min_rpm,
            max_rpm=dto.max_rpm,
            state=state_str
        )