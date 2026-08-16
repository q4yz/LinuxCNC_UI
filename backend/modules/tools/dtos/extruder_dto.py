from dataclasses import dataclass
from typing import Optional
from dtos.HalPin import HalPin, UnconnectedHalPin
from modules.tools.dtos.heater_dto import HeaterPins, HeaterStateDTO, HeaterSettingsDTO


@dataclass(frozen=True, slots=True)
class ExtruderPins:
    id: str
    heater: HeaterPins
    position: HalPin = UnconnectedHalPin()

@dataclass(frozen=True, slots=True)
class ExtruderStateDTO:
    id: str
    heater: HeaterStateDTO
    position: float = 0.0

@dataclass(slots=True)
class ExtruderSettingsDTO:
    """Payload for commanding the extruder to a new state.

    ``heater`` is optional: ``None`` means the caller chose
    ``heater_action="noop"`` and the dispatch must skip the heater
    target write. A non-None value drives the heater to the new
    target before the move.
    """
    id: str
    heater: Optional[HeaterSettingsDTO]
    relative_distance: float = 0.0