from typing import Dict, Any

from dtos.HalPin import DynamicHalPin
from modules.tools.dtos.extruder_dto import ExtruderPins, ExtruderStateDTO

from modules.tools.mapper.heater_mapper import HeaterMapper  # Adjust import path
from modules.tools.mapper.as_optional_mappers import OptionalMappers


class ExtruderMapper:

    @classmethod
    def from_dict_to_ExtruderPins(cls, data: Dict[str, Any]) -> ExtruderPins:
        tool_id = str(data["id"])

        position_val = data.get("position", f"{tool_id}_position")

        return ExtruderPins(
            id=tool_id,
            heater=HeaterMapper.from_dict_to_HeaterPins(data),
            position=DynamicHalPin(str(position_val)),
        )

    @classmethod
    def to_state_dto(cls, halpin: ExtruderPins) -> ExtruderStateDTO:
        return ExtruderStateDTO(
            id=halpin.id,
            heater=HeaterMapper.to_state_dto(halpin.heater),
            position=OptionalMappers.as_float(halpin.position.get_value()),
        )