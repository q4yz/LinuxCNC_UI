from dataclasses import dataclass
from typing import Optional, TypeVar

from dtos.pins.HalPin import HalPin

T = TypeVar('T')

@dataclass(frozen=True, slots=True)
class StaticHalPin(HalPin[T]):
    """A hardcoded configuration value."""
    value: T
    pin: Optional[str] = None

    def __post_init__(self):
        self.check_and_register(self.pin)

    def is_static(self) -> bool:
        return True

    def get_value(self) -> Optional[T]:
        return self.value

    def get_doc_string(self) -> str:
        return f"StaticHalPin"
