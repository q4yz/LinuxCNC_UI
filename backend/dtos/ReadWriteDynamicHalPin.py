from dataclasses import dataclass
from typing import TypeVar, Optional

from dtos.HalPin import HalDataType, HalPin, logger
from hardware import hal
from hardware.connection import read_hal_pin

T = TypeVar('T')

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