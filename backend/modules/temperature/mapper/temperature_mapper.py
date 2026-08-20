from typing import Dict, Any

from dtos.HalPin import ReadWriteDynamicHalPin
from modules.temperature.dtos.temperature_dto import SensorPin, SensorStateDto
from modules.temperature.models.temperature_models import TemperatureStateResponse
from modules.tools.mapper.as_optional_mappers import OptionalMappers




class TemperatureSensorMapper:

    @classmethod
    def from_dict_to_TemperaturePins(cls, data: Dict[str, Any]) -> SensorPin:
        """Translates the hardware.json dictionary into a SensorPin dataclass."""
        sensor_id = str(data["id"])

        suffix = sensor_id.replace("sensor", "")

        pin_name = data.get("pin", f"actual-temperature{suffix}")

        return SensorPin(
            id=sensor_id,
            actual_temperature=ReadWriteDynamicHalPin(pin_name)
        )

    @classmethod
    def to_state_dto(cls, halpin: SensorPin) -> SensorStateDto:
        """Reads the HAL pins and translates them into the runtime State DTO."""
        return SensorStateDto(
            id=halpin.id,
            actual_temperature=OptionalMappers.as_float(halpin.actual_temperature.get_value())
        )

    @classmethod
    def to_response(cls, dto: SensorStateDto) -> TemperatureStateResponse:
        """Reads the HAL pins and translates them into the runtime State DTO."""
        return TemperatureStateResponse(tool_id = dto.id,
            actual = dto.actual_temperature)