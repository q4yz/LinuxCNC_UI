from dataclasses import dataclass

from dtos.pins.HalPin import HalPin
from dtos.pins.UnconnectedHalPin import UnconnectedHalPin


@dataclass(frozen=True, slots=True)
class PauseInspectPin:
    id: str
    inspect_z_lift: HalPin[bool] = UnconnectedHalPin()
    inspect_spindle_inhibit: HalPin[bool] = UnconnectedHalPin()