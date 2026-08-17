import logging

from hardware.mock.tools.mock_exrtruder import MockExtruder
from hardware.mock.tools.mock_heater import MockHeater
from hardware.mock.tools.mock_spindle_digital import MockSpindleDigital

logger = logging.getLogger("backend.hardware.mock.factory")


class MockToolFactory:
    """Factory to instantiate the correct OOP mock component from a hardware payload."""

    @staticmethod
    def create(tool_record: dict):
        """Creates a mock component based on the tool's configured type."""

        tool_type = tool_record.get("type", "")
        tool_id = tool_record.get("id")

        if not tool_id:
            logger.warning("Tool record missing 'id' field, skipping.")
            return None

        if tool_type == "extruder":
            return MockExtruder(tool_id=tool_id)

        elif tool_type in ("heater", "heated_bed"):
            return MockHeater(tool_id=tool_id)


        elif tool_type in ("spindle", "spindle_digital"):
            return MockSpindleDigital(tool_id=tool_id)


        logger.debug(  "No OOP mock component registered for tool type %r (tool_id: %r)",tool_type, tool_id)
        return None