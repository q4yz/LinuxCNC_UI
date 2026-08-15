from typing import Dict, Any

from dtos.HalPin import DynamicHalPin, StaticHalPin, UnconnectedHalPin
from modules.tools.dtos.heater_dto import HeaterStateDTO, HeaterPins
from modules.tools.mapper.as_optional_mappers import OptionalMappers


class HeaterMapper:

    @classmethod
    def from_dict_to_HeaterPins(cls, data: Dict[str, Any]) -> HeaterPins:
        tool_id = str(data["id"])

        fan_val = data.get("fan")

        # Mapping actual temperature to the 'sensor' key from your JSON payload,
        # and generating a default target_temperature pin if not explicitly provided.
        actual_temp_val = data.get("sensor", f"{tool_id}_actual")
        target_temp_val = data.get("target_temperature", f"{tool_id}_target")

        return HeaterPins(
            id=tool_id,
            target_temperature=DynamicHalPin(str(target_temp_val)),
            actual_temperature=DynamicHalPin(str(actual_temp_val)),
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