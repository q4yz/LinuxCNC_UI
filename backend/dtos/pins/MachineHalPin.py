from dataclasses import dataclass
from typing import Optional, TypeVar

from dtos.pins.HalPin import HalPin, HalDirection



T = TypeVar('T')

@dataclass(frozen=True, slots=True)
class MachineHalPin(HalPin[T]):
    """Is used for the visual ui editor not for pin registration"""
    value: T
    pin: Optional[str] = None
    component: str = ""
    description: str = ""
    direction: HalDirection = HalDirection.IN



    def get_value(self) -> Optional[T]:
        return self.value

    def get_doc_string(self) -> str:
        return self.description

    def get_direction(self) -> HalDirection:
        return self.direction

    def get_comp_name(self) -> str:
        return self.component if self.component is not None else ""

    def get_pin_name(self) -> str:
        return self.pin if self.pin is not None else ""

