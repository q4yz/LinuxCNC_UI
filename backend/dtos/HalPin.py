import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, TypeVar, Generic, ClassVar

from hardware.connection import read_hal_pin, execute_sync_cmd

T = TypeVar('T')

logger = logging.getLogger(__name__)

class HalPin(ABC, Generic[T]):
    """Base interface for all HAL properties."""

    _registered_pins: ClassVar[set[str]] = set()

    @classmethod
    def check_and_register(cls, pin_name: str) -> None:
        """Registers a pin name and warns if it is already in use."""
        if not pin_name:
            return

        if pin_name in cls._registered_pins:
            logger.warning("HAL Pin double registration detected for pin: '%s'", pin_name)
        else:
            cls._registered_pins.add(pin_name)

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

    def __post_init__(self):
        self.check_and_register(self.pin)

    def is_static(self) -> bool:
        return True

    def get_value(self) -> Optional[T]:
        return self.value



@dataclass(frozen=True, slots=True)
class DynamicHalPin(HalPin[T]):
    """A dynamic HAL signal name to be connected."""
    pin: str

    def __post_init__(self):
        self.check_and_register(self.pin)

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


@dataclass(frozen=True, slots=True)
class ReadOnlyDynamicHalPin(HalPin[T]):
    """A dynamic HAL signal name that can only be read, not written."""
    pin: str

    def __post_init__(self):
        self.check_and_register(self.pin)

    def is_static(self) -> bool:
        return False

    def get_value(self) -> Optional[T]:
        return read_hal_pin(self.pin)

    def set_value(self, value: T) -> None:
        raise PermissionError(f"Operation not allowed: {self.__class__.__name__} is read-only.")
