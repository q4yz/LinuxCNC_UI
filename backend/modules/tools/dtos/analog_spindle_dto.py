from dataclasses import dataclass
from dtos.HalPin import HalPin, UnconnectedHalPin

@dataclass(frozen=True, slots=True)
class SpindleAnalogPins:
    id: str
    analog_out: HalPin = UnconnectedHalPin()
    target_rpm: HalPin = UnconnectedHalPin()
    min_rpm: HalPin = UnconnectedHalPin()
    max_rpm: HalPin = UnconnectedHalPin()

@dataclass(frozen=True, slots=True)
class SpindleAnalogStateDTO:
    id: str
    analog_out: float = 0.0
    target_rpm: float = 0.0
    min_rpm: float = 0.0
    max_rpm: float = 0.0

@dataclass(slots=True)
class SpindleAnalogSettingsDTO:
    id: str
    percent: float