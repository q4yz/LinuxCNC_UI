from typing import Dict, Any

from dtos.pins.HalPin import  HalDataType
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from dtos.pins.StaticHalPin import StaticHalPin
from dtos.tools import SpindleAnalogPins
from dtos.tools.SpindleAnalogDto import SpindleAnalogStateDTO
from mappers.tools.OptionalMappers import OptionalMappers


class SpindleAnalogMapper():

    @classmethod
    def from_dict_to_SpindleAnalogPins(cls, data: Dict[str, Any]) -> SpindleAnalogPins:
        tool_id = str(data["id"])
        suffix = tool_id.replace("spindle_analog", "")

        return SpindleAnalogPins(
            id=tool_id,
            analog_out=ReadWriteDynamicHalPin(f"analog-out{suffix}", HalDataType.FLOAT),
            target_rpm=ReadWriteDynamicHalPin(f"TargetRpm{suffix}", HalDataType.FLOAT),
            min_rpm=StaticHalPin(OptionalMappers.as_optional_number(data.get("min_rpm"), int) or 0),
            max_rpm=StaticHalPin(OptionalMappers.as_optional_number(data.get("max_rpm"), int) or 24000),
        )

    @classmethod
    def to_state_dto(cls, halpin: SpindleAnalogPins) -> SpindleAnalogStateDTO:

        return SpindleAnalogStateDTO(
            id=halpin.id,
            analog_out=OptionalMappers.as_float(halpin.analog_out.get_value()),
            target_rpm=OptionalMappers.as_float(halpin.target_rpm.get_value()),
            min_rpm=OptionalMappers.as_float(halpin.min_rpm.get_value()),
            max_rpm=OptionalMappers.as_float(halpin.max_rpm.get_value()),
        )