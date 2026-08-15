import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, TypeVar, Generic

from hardware.connection import read_hal_pin, execute_sync_cmd

T = TypeVar('T')

class HalPin(ABC, Generic[T]):
    """Base interface for all HAL properties."""

    @abstractmethod
    def is_static(self) -> bool:
        """Returns True if this is just a static value, not a dynamic pin."""
        pass

    @abstractmethod
    def get_value(self) -> Optional[T]:
        """Returns the value (static or read from HAL), strictly typed."""
        pass

    def set_value(self, value: T) -> None:
        raise NotImplementedError(f"{self.__class__.__name__} is read-only and cannot be set.")

@dataclass(frozen=True, slots=True)
class StaticHalPin(HalPin[T]):
    """A hardcoded configuration value."""
    value: T
    pin: Optional[str] = None

    def is_static(self) -> bool:
        return True

    def get_value(self) -> Optional[T]:
        return self.value



@dataclass(frozen=True, slots=True)
class DynamicHalPin(HalPin[T]):
    """A dynamic HAL signal name to be connected."""
    pin: str

    def is_static(self) -> bool:
        return False

    def get_value(self) -> Optional[T]:
        return read_hal_pin(self.pin)

    def set_value(self, value: T) -> None:
        logging.info("HAL setp -> %s = %s", self.pin, value)
        execute_sync_cmd("setp", 0, self.pin, value)

@dataclass(frozen=True, slots=True)
class UnconnectedHalPin(HalPin[Any]):
    """Represents a pin that is intentionally left blank."""

    def is_static(self) -> bool:
        return True

    def get_value(self) -> None:
        return None


