from dataclasses import dataclass

from dtos.pins.HalPin import HalPin
from dtos.pins.UnconnectedHalPin import UnconnectedHalPin


@dataclass(frozen=True, slots=True)
class FanPins:
    id: str
    speed: HalPin[float] = UnconnectedHalPin()
