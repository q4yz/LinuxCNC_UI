from dataclasses import dataclass
from typing import Optional, Union, Any, Dict

from dtos.HalPin import HalPin, UnconnectedHalPin, DynamicHalPin, StaticHalPin


@dataclass(frozen=True, slots=True)
class HeaterPins:
    id: str
    heater_pin: HalPin = UnconnectedHalPin()
    sensor: HalPin = UnconnectedHalPin()
    fan: HalPin = UnconnectedHalPin()
    min_temp: HalPin = UnconnectedHalPin()
    max_temp: HalPin = UnconnectedHalPin()

    @classmethod
    def _as_optional_number(cls, value: Any, num_type: type) -> Optional[Union[int, float]]:
        if isinstance(value, (int, float)):
            return num_type(value)
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            try:
                return num_type(float(value))
            except ValueError:
                return None
        return None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HeaterPins":
        tool_id = str(data["id"])

        # Using dict.get() for hardware config values to safely build the pins
        heater_pin_val = data.get("heater_pin")
        sensor_val = data.get("sensor")
        fan_val = data.get("fan")

        return cls(
            id=tool_id,
            heater_pin=DynamicHalPin(heater_pin_val) if heater_pin_val else UnconnectedHalPin(),
            sensor=DynamicHalPin(sensor_val) if sensor_val else UnconnectedHalPin(),
            fan=DynamicHalPin(fan_val) if fan_val else UnconnectedHalPin(),
            min_temp=StaticHalPin(cls._as_optional_number(data.get("min_temp"), float) or 0.0),
            max_temp=StaticHalPin(cls._as_optional_number(data.get("max_temp"), float) or 300.0),
        )