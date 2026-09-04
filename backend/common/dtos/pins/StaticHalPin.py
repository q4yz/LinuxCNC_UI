from dataclasses import dataclass
from typing import Optional, TypeVar

from dtos.pins.HalPin import HalPin, HalDirection

T = TypeVar('T')

@dataclass(frozen=True, slots=True)
class StaticHalPin(HalPin[T]):
    """A hardcoded configuration value."""
    value: T
    pin: Optional[str] = None

    def __post_init__(self):
        self.check_and_register(self.pin)

    def get_value(self) -> Optional[T]:
        return self.value

    def get_doc_string(self) -> str:
        return f"StaticHalPin"

    def get_direction(self) -> HalDirection:
        return HalDirection.OUT

    def get_pin_name(self) -> str:
        return self.pin
