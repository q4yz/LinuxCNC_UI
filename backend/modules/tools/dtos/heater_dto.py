from dataclasses import dataclass
from dtos.HalPin import HalPin, UnconnectedHalPin


@dataclass(frozen=True, slots=True)
class HeaterPins:
    id: str
    target_temperature: HalPin[float] = UnconnectedHalPin()
    actual_temperature: HalPin[float] = UnconnectedHalPin()
    fan: HalPin = UnconnectedHalPin()
    min_temp: HalPin = UnconnectedHalPin()
    max_temp: HalPin = UnconnectedHalPin()

@dataclass(frozen=True, slots=True)
class HeaterStateDTO:
    """Operator-facing snapshot of the heater's live state."""
    id: str
    target_temperature: float = 0.0
    actual_temperature: float = 0.0
    fan: float = 0.0
    min_temp: float = 0.0
    max_temp: float = 0.0

@dataclass(slots=True)
class HeaterSettingsDTO:
    """Payload for commanding the heater to a new target temperature."""
    id: str
    target_temperature: float
    enable: bool = True


