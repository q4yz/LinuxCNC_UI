import logging
from typing import Any, Optional

from hardware.mock.config import MockHeaterConfig
from hardware.mock.tools.MockComponent import MockComponent
from hardware.mock.tools.MockExtruder import MockExtruder
from hardware.mock.tools.MockHeater import MockHeater
from hardware.mock.tools.MockSpindleDigital import MockSpindleDigital

logger = logging.getLogger("backend.hardware.mock.factory")


class MockToolFactory:
    """The mock component simulating one ``hardware.json`` tool."""

    @staticmethod
    def create(tool_record: dict[str, Any], heater: Optional[MockHeaterConfig] = None) -> Optional[MockComponent]:
        tool_type = tool_record.get("type", "")
        tool_id = tool_record.get("id")
        if not tool_id:
            logger.warning("Tool record missing 'id' field, skipping.")
            return None
        # The heater reads its sensor's pin (HeaterMapper), so the mock
        # publishes the reading there.
        sensor_id = tool_record.get("sensor")
        max_temp = heater.max_temp if heater else None
        if tool_type == "extruder":
            return MockExtruder(tool_id=tool_id, sensor_id=sensor_id, max_temp=max_temp)
        if tool_type in ("heater", "heated_bed"):
            return MockHeater(id=tool_id, sensor_id=sensor_id, max_temp=max_temp)
        if tool_type in ("spindle", "spindle_digital"):
            return MockSpindleDigital(tool_id=tool_id)
        logger.debug("No mock component for tool type %r (tool_id: %r)", tool_type, tool_id)
        return None
