from dataclasses import dataclass
from typing import Dict, Any, Optional, Union

from dtos.HalPin import HalPin, UnconnectedHalPin, DynamicHalPin, StaticHalPin


@dataclass(frozen=True, slots=True)
class SpindleAnalogPins:
    id: str
    analog_out: HalPin = UnconnectedHalPin()
    target_rpm: HalPin = UnconnectedHalPin()
    actual_rpm: HalPin = UnconnectedHalPin()
    min_rpm: HalPin = UnconnectedHalPin()
    max_rpm: HalPin = UnconnectedHalPin()

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
    def from_dict(cls, data: Dict[str, Any]) -> "SpindleAnalogPins":
        tool_id = str(data["id"])
        suffix = tool_id.replace("spindle_analog", "")
        return cls(
            id=tool_id,
            analog_out=DynamicHalPin(f"analog-out{suffix}"),
            target_rpm=DynamicHalPin(f"TargetRpm{suffix}"),
            actual_rpm=DynamicHalPin(f"rpm-out{suffix}"),
            min_rpm=StaticHalPin(cls._as_optional_number(data.get("min_rpm"), int) or 0),
            max_rpm=StaticHalPin(cls._as_optional_number(data.get("max_rpm"), int) or 24000),
        )