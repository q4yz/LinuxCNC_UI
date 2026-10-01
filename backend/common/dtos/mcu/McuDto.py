from dataclasses import dataclass

from dtos.pins.HalPin import HalPin
from dtos.pins.UnconnectedHalPin import UnconnectedHalPin


@dataclass(frozen=True, slots=True)
class McuPins:
    """One ``hardware.json`` ``mcus[]`` record's runtime surface.

    ``reset`` is only a real pin (``webgui.<id>-reset``) on a board
    that can be reset from the UI — a Remora MCU that declared a
    ``reset_pin``. Every other MCU keeps the unconnected placeholder
    and ``resettable`` stays ``False``.
    """
    id: str
    connection: str
    resettable: bool = False
    reset: HalPin[bool] = UnconnectedHalPin()
