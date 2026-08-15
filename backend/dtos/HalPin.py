from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, Union

from hardware.connection import read_hal_pin


class HalPin(ABC):
    """Base interface for all HAL properties."""

    @abstractmethod
    def is_static(self) -> bool:
        """Returns True if this is just a static value, not a dynamic pin."""
        pass

    @abstractmethod
    def get_value(self) -> Any:
        """Returns the value (static or read from HAL)."""
        pass


@dataclass(frozen=True, slots=True)
class StaticHalPin(HalPin):
    """A hardcoded configuration value (e.g., 5000, 24000, True, 0)."""
    # Put required fields first, Optional/defaults second
    value: Union[int, float, bool, str]
    pin: Optional[str] = None

    def is_static(self) -> bool:
        return True

    def get_value(self) -> Optional[object]:
        return self.value


@dataclass(frozen=True, slots=True)
class DynamicHalPin(HalPin):
    """A dynamic HAL signal name to be connected (e.g., 'rpm-out_test')."""
    pin: str

    def is_static(self) -> bool:
        return False

    def get_value(self) -> Optional[object]:

        return read_hal_pin(self.pin)


@dataclass(frozen=True, slots=True)
class UnconnectedHalPin(HalPin):
    """Represents a pin that is intentionally left blank."""

    def is_static(self) -> bool:
        return True

    def get_value(self) -> Optional[object]:
        return None