from typing import Dict, Any

from dtos.HalPin import DynamicHalPin, StaticHalPin
from modules.tools.dtos import SpindleDigitalPins, SpindleDigitalStateDTO
from modules.tools.mapper.as_optional_mappers import OptionalMappers


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