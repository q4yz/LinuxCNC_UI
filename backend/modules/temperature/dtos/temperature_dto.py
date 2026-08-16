from dataclasses import dataclass

from dtos.HalPin import HalPin, UnconnectedHalPin


@dataclass(frozen=True, slots=True)
class SensorPin:
    id: str
    actual_temperature: HalPin = UnconnectedHalPin()

@dataclass(frozen=True, slots=True)
class SensorStateDto:
    id: str
    actual_temperature: float = 0.0