from dataclasses import dataclass
from typing import Optional, TypeVar

from dtos.HalPin import HalPin, HalDataType
from hardware import hal
from hardware.Connection import read_hal_pin

T = TypeVar('T')

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