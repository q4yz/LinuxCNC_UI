from dataclasses import dataclass
from dtos.pins.HalPin import HalPin
from dtos.pins.UnconnectedHalPin import UnconnectedHalPin


@dataclass(frozen=True, slots=True)
class SpindleAnalogPins:
    id: str
    analog_out: HalPin[float] = UnconnectedHalPin()
    target_rpm: HalPin[float] = UnconnectedHalPin()
    min_rpm: HalPin[float] = UnconnectedHalPin()
    max_rpm: HalPin[float] = UnconnectedHalPin()

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