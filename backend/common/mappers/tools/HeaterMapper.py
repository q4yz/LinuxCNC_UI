from typing import Dict, Any, TYPE_CHECKING

from core.field_masking import ResponseTier, include_base, include_static
from dtos.pins.HalPin import  HalDataType
from dtos.pins.ReadOnlyDynamicHalPin import ReadOnlyDynamicHalPin
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from dtos.pins.StaticHalPin import StaticHalPin
from dtos.pins.UnconnectedHalPin import UnconnectedHalPin
from dtos.tools.HeaterDto import HeaterStateDTO, HeaterPins, HeaterSettingsDTO
from mappers.tools.OptionalMappers import OptionalMappers
from models.tools.HeaterModels import HeaterStateResponse

if TYPE_CHECKING:
    from routers.tools import HeaterCommand


class HeaterMapper:

    @classmethod
    def from_dict_to_HeaterPins(cls, data: Dict[str, Any]) -> HeaterPins:
        """Build the heater's HAL surface from its ``hardware.json`` entry.

        The heater does not own its reading — it *carries a sensor*. The
        ``sensor`` field names a ``temperature_sensors[]`` entry, and that
        sensor's pin (``webgui.<sensor_id>``, see
        :class:`TemperatureSensorMapper`) is what the heater reads. One
        thermistor is therefore one HAL pin with two readers (the heater
        tool and the sensor entity) instead of two pins carrying the same
        value, which had to be wired twice and could disagree.

        A heater with no ``sensor`` keeps the derived
        ``actual-temperature<suffix>`` name so sensor-less configs still work.
        """
        tool_id = str(data["id"])
        suffix = tool_id.replace("heater", "")
        fan_val = data.get("fan")
        sensor_id = data.get("sensor")
        actual_pin = str(sensor_id) if sensor_id else f"actual-temperature{suffix}"

        return HeaterPins(
            id=tool_id,
            target_temperature=ReadWriteDynamicHalPin(f"target-temperature{suffix}", HalDataType.FLOAT, ""),
            # The heater doesn't drive this value — the MCU router's
            # sensor pin (`remora.PV.N`) is the real HAL_OUT writer;
            # webgui only reads it. Registering this as a
            # ReadWriteDynamicHalPin (HAL_OUT) made `webgui.<sensor_id>`
            # fight `remora.PV.N` for ownership of the same signal — a
            # genuine HAL load error ("can not add OUT pin ... it
            # already has OUT pin"), not a cosmetic one.
            actual_temperature=ReadOnlyDynamicHalPin(actual_pin, HalDataType.FLOAT, ""),
            fan=ReadWriteDynamicHalPin(str(fan_val), HalDataType.FLOAT, "") if fan_val else UnconnectedHalPin(),
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

    @classmethod
    def from_command_to_settings_dto(cls, cmd: "HeaterCommand") -> HeaterSettingsDTO:
        """Translates the HTTP heater command into the internal domain DTO."""
        return HeaterSettingsDTO(
            id=cmd.id,
            target_temperature=cmd.target,
            enable=(cmd.target > 0.0)
        )

    @classmethod
    def to_response(cls, dto: HeaterStateDTO, r : ResponseTier = ResponseTier.ALL) -> HeaterStateResponse:
        return HeaterStateResponse(
            id=dto.id,
            target= include_base(dto.target_temperature, r),
            actual=include_base(dto.actual_temperature, r),
            min_temp=include_static( dto.min_temp, r),
            max_temp=include_static( dto.max_temp, r)
        )

