from typing import Dict, Any

from core.field_masking import ResponseTier, include_base
from dtos.pins.HalPin import HalDataType
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from dtos.sensors.TemperatureDto import TemperaturePin, TemperatureStateDto
from models.temperature_response import TemperatureStateResponse
from mappers.tools.OptionalMappers import OptionalMappers




class TemperatureSensorMapper:

    @classmethod
    def from_dict_to_TemperaturePins(cls, data: Dict[str, Any]) -> TemperaturePin:
        """Translates the hardware.json dictionary into a SensorPin dataclass."""
        sensor_id = str(data["id"])

        suffix = sensor_id.replace("sensor", "")

        pin_name = data.get("pin", f"actual-temperature{suffix}")

        return TemperaturePin(
            id=sensor_id,
            actual_temperature=ReadWriteDynamicHalPin[float](pin_name, HalDataType.FLOAT)
        )

    @classmethod
    def to_state_dto(cls, halpin: TemperaturePin) -> TemperatureStateDto:
        """Reads the HAL pins and translates them into the runtime State DTO."""
        return TemperatureStateDto(
            id=halpin.id,
            actual_temperature=OptionalMappers.as_float(halpin.actual_temperature.get_value())
        )

    @classmethod
    def to_response(cls, dto: TemperatureStateDto, r : ResponseTier = ResponseTier.ALL) -> TemperatureStateResponse:
        """Reads the HAL pins and translates them into the runtime State DTO."""
        return TemperatureStateResponse(id = dto.id,
            actual = include_base(dto.actual_temperature , r) )