from typing import Dict, Any

from core.field_masking import ResponseTier, include_base
from dtos.pins.HalPin import HalDataType
from dtos.pins.ReadOnlyDynamicHalPin import ReadOnlyDynamicHalPin
from dtos.sensors.TemperatureDto import TemperaturePin, TemperatureStateDto
from models.temperature_response import TemperatureStateResponse
from mappers.tools.OptionalMappers import OptionalMappers




class TemperatureSensorMapper:

    @classmethod
    def from_dict_to_TemperaturePins(cls, data: Dict[str, Any]) -> TemperaturePin:
        """Translates the hardware.json dictionary into a SensorPin dataclass.

        The HAL pin is named after the sensor's id (``webgui.<id>``),
        never after ``temperature_sensors[].pin``. That field holds the
        *MCU* pin the thermistor is physically wired to (``"PA1"``) —
        it belongs to the compiler, which routes ``webgui.<id>`` to
        ``<mcu>.PA1``. Reading it here produced HAL pins literally
        called ``webgui.PA1``.
        """
        sensor_id = str(data["id"])

        # A sensor's reading is written by the MCU router
        # (`remora.PV.N`, a real HAL_OUT) — webgui only reads it, so
        # this must be HAL_IN. Registering it ReadWrite (HAL_OUT) made
        # `webgui.<id>` fight the router's own pin for ownership of
        # the signal, a HAL load-time error, not a cosmetic one.
        return TemperaturePin(
            id=sensor_id,
            actual_temperature=ReadOnlyDynamicHalPin[float](sensor_id, HalDataType.FLOAT, "")
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