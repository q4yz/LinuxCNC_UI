from typing import Dict, Any

from dtos.HalPin import ReadWriteDynamicHalPin, StaticHalPin, ReadOnlyDynamicHalPin, HalDataType
from modules.tools.dtos import SpindleDigitalPins, SpindleDigitalStateDTO
from modules.tools.dtos.digital_spindle_dto import DirectionStateType, SpindleDigitalSettingsDTO
from modules.tools.mapper.as_optional_mappers import OptionalMappers
from modules.tools.models.spindel_digital_models import SpindleDigitalCommand, SpindleDigitalStateResponse


class SpindleDigitalMapper():

    @classmethod
    def from_dict_to_SpindleDigitalPins(cls, data: Dict[str, Any]) -> SpindleDigitalPins:
        tool_id = str(data["id"])
        suffix = tool_id.replace("spindle_digital", "")

        return SpindleDigitalPins(
            id=tool_id,
            spindle_at_speed=ReadOnlyDynamicHalPin(f"spindle-at-speed{suffix}", HalDataType.BIT),
            target_rpm=ReadOnlyDynamicHalPin(f"TargetRpm{suffix}",HalDataType.FLOAT),
            actual_rpm=ReadOnlyDynamicHalPin(f"rpm-out{suffix}", HalDataType.FLOAT),
            is_connected=ReadOnlyDynamicHalPin(f"is-connected{suffix}", HalDataType.BIT),
            error_count=ReadOnlyDynamicHalPin(f"error-count{suffix}", HalDataType.S32),
            last_error=ReadOnlyDynamicHalPin(f"last-error{suffix}", HalDataType.S32),
            min_rpm=StaticHalPin(OptionalMappers.as_optional_number(data.get("min_rpm"), int) or 0),
            max_rpm=StaticHalPin(OptionalMappers.as_optional_number(data.get("max_rpm"), int) or 24000),
            spindle_forward=ReadOnlyDynamicHalPin(f"spindle-forward{suffix}", HalDataType.BIT),
            spindle_reverse=ReadOnlyDynamicHalPin(f"spindle-reverse{suffix}", HalDataType.BIT),
            absolute_master_override_enable=ReadWriteDynamicHalPin(f"absolute-master-override-enable{suffix}", HalDataType.BIT),
            absolute_master_override=ReadWriteDynamicHalPin(f"absolute-master-override{suffix}", HalDataType.FLOAT),
            override=ReadWriteDynamicHalPin(f"override{suffix}", HalDataType.FLOAT),
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
            absolute_master_override_enable = OptionalMappers.as_bool(halpin.absolute_master_override_enable.get_value()),
            absolute_master_override = OptionalMappers.as_float(halpin.absolute_master_override.get_value()),
            override=OptionalMappers.as_bool(halpin.override.get_value()),
        )

    @classmethod
    def from_command_to_settings_dto(cls, cmd: "SpindleDigitalCommand") -> SpindleDigitalSettingsDTO:
        """Translates the HTTP command payload into the strict internal domain DTO."""

        action_map = {
            "forward": DirectionStateType.FORWARD,
            "backward": DirectionStateType.BACKWARD,
            "stop": DirectionStateType.IDLE,
        }

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