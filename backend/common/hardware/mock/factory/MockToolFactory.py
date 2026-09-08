import logging
from typing import Any

from hardware.mock.tools.MockExtruder import MockExtruder
from hardware.mock.tools.MockHeater import MockHeater
from hardware.mock.tools.MockSpindleDigital import MockSpindleDigital

logger = logging.getLogger("backend.hardware.mock.factory")


class MockToolFactory:
    """Factory to instantiate the correct OOP mock component from a hardware payload."""

    @staticmethod
    def create(tool_record: dict[str, Any]):
        """Creates a mock component based on the tool's configured type."""

        tool_type = tool_record.get("type", "")
        tool_id = tool_record.get("id")

        if not tool_id:
            logger.warning("Tool record missing 'id' field, skipping.")
            return None

        # The heater reads its sensor's pin, so the mock has to publish
        # on that pin too — see HeaterMapper.from_dict_to_HeaterPins.
        sensor_id = tool_record.get("sensor")

        if tool_type == "extruder":
            return MockExtruder(tool_id=tool_id, sensor_id=sensor_id)

        elif tool_type in ("heater", "heated_bed"):
            return MockHeater(id=tool_id, sensor_id=sensor_id)


        elif tool_type in ("spindle", "spindle_digital"):
            return MockSpindleDigital(tool_id=tool_id)


        logger.debug(  "No OOP mock component registered for tool type %r (tool_id: %r)",tool_type, tool_id)
        return None