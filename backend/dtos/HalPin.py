import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, TypeVar, Generic, ClassVar

from hardware import hal
from hardware.connection import read_hal_pin

T = TypeVar('T')

logger = logging.getLogger(__name__)


class HalDataType(Enum):
    """Domain-level representation of LinuxCNC HAL pin data types."""
    BIT = "BIT"
    FLOAT = "FLOAT"
    S32 = "S32"
    U32 = "U32"

    def to_hal_constant(self) -> int:
        """Translates the enum to the actual C-extension constant."""
        if self == HalDataType.BIT: return hal.HAL_BIT
        if self == HalDataType.FLOAT: return hal.HAL_FLOAT
        if self == HalDataType.S32: return hal.HAL_S32
        if self == HalDataType.U32: return hal.HAL_U32
        raise ValueError(f"Unknown HAL data type: {self}")


class HalPin(ABC, Generic[T]):
    """Base interface for all HAL properties."""
    _component_name: str = "webgui"
    _comp_instance: Any = None
    _registered_pins: ClassVar[set[str]] = set()
    _pending_pins: ClassVar[list[tuple[str, int, int]]] = []

    @classmethod
    def initialize_component(cls) -> None:
        """
        Initialize the HAL component, create all queued pins, and lock it.
        Call this ONCE in your FastAPI lifespan.
        """
        if cls._comp_instance is not None:
            return

        cls._comp_instance = hal.component(cls._component_name)
        logger.info("HAL Component '%s' initialized.", cls._component_name)

        for pin_name, hal_type, hal_dir in cls._pending_pins:
            cls._comp_instance.newpin(pin_name, hal_type, hal_dir)
            logger.debug("Created pin: %s.%s", cls._component_name, pin_name)

        cls._comp_instance.ready()
        logger.info("HAL Component '%s' is ready with %d pins.", cls._component_name, len(cls._pending_pins))

    @classmethod
    def check_and_register(cls, pin_name: str, hal_type: Optional[HalDataType] = None, hal_dir: Optional[int] = None) -> None:
        """Registers a pin name. If it's dynamic, queues it for creation."""
        if not pin_name:
            return

        if pin_name in cls._registered_pins:
            logger.warning("HAL Pin double registration detected for pin: '%s'", pin_name)
            return

        cls._registered_pins.add(pin_name)

        if hal_type is not None and hal_dir is not None:
            cls._pending_pins.append((pin_name, hal_type.to_hal_constant(), hal_dir))

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
class ReadWriteDynamicHalPin(HalPin[T]):
    """A dynamic HAL signal name to be connected."""
    pin: str
    hal_type: HalDataType

    def __post_init__(self):
        self.check_and_register(self.pin, self.hal_type, hal.HAL_OUT)

    def is_static(self) -> bool:
        return False

    def get_value(self) -> Optional[T]:
        return read_hal_pin(f"{HalPin._component_name}.{self.pin}")

    def set_value(self, value: T) -> None:
        full_pin_name = f"{HalPin._component_name}.{self.pin}"

        if HalPin._comp_instance is None:
            logger.error("Cannot set %s: HAL component not initialized. Did you call HalPin.initialize_component()?",
                         full_pin_name)
            return

        try:
            HalPin._comp_instance[self.pin] = value
            logger.info("HAL write native -> %s = %s", full_pin_name, value)
        except Exception as e:
            logger.error("Failed to write native HAL pin '%s': %s", full_pin_name, e)


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
    hal_type: HalDataType

    def __post_init__(self):
        self.check_and_register(self.pin, self.hal_type, hal.HAL_IN)

    def is_static(self) -> bool:
        return False

    def get_value(self) -> Optional[T]:
        return read_hal_pin(f"{HalPin._component_name}.{self.pin}")

    def set_value(self, value: T) -> None:
        raise PermissionError(f"Operation not allowed: {self.__class__.__name__} is read-only.")