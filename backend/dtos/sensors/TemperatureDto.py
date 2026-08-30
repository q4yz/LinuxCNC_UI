from dataclasses import dataclass

from dtos.pins.HalPin import HalPin
from dtos.pins.UnconnectedHalPin import UnconnectedHalPin


@dataclass(frozen=True, slots=True)
class TemperaturePin:
    id: str
    actual_temperature: HalPin[float] = UnconnectedHalPin()

@dataclass(frozen=True, slots=True)
class TemperatureStateDto:
    id: str
    actual_temperature: float = 0.0