from typing import Dict, Any, Optional, Union

from modules.tools.dtos.analog_spindle_dto import SpindleAnalogPins
from modules.tools.dtos.digital_spindle_dto import SpindleDigitalPins
from modules.tools.dtos.extruder_dto import HeaterPins




ToolPins = Union[SpindleDigitalPins, SpindleAnalogPins, HeaterPins]

class ToolHalPinFactory:

    @staticmethod
    def create(data: Dict[str, Any]) -> Optional[ToolPins]:
        tool_type = data.get("type")
        tool_id = data.get("id")

        if not isinstance(tool_type, str) or not isinstance(tool_id, str) or not tool_id:
            return None

        if tool_type == "spindle_digital":
            return SpindleDigitalPins.from_dict(data)

        elif tool_type == "spindle_analog":
            return SpindleAnalogPins.from_dict(data)

        elif tool_type in ("extruder", "heated_bed"):
            return HeaterPins.from_dict(data)

        return None