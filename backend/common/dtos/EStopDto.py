from dataclasses import dataclass

from dtos.pins.HalPin import HalPin
from dtos.pins.UnconnectedHalPin import UnconnectedHalPin


@dataclass(frozen=True, slots=True)
class EStopPin:
    id: str
    pressed: HalPin[bool] = UnconnectedHalPin()