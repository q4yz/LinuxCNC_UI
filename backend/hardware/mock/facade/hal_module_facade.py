from typing import Any

from hardware.mock.facade.MockHalComponent import MockComponent
from hardware.mock.hal_mock import HalMock


class HalModuleFacade:
    """A drop-in replacement for the real LinuxCNC 'hal' Python module.

    This object is exposed to the rest of the application (e.g., via
    hardware.connection). When the application calls hal.get_value(),
    it secretly reads from our internal HalMock simulation.
    """

    HAL_IN: int = 1
    HAL_OUT: int = 2
    HAL_IO: int = 3

    HAL_BIT: int = 1
    HAL_FLOAT: int = 2
    HAL_S32: int = 3
    HAL_U32: int = 4

    def __init__(self, internal_hal: HalMock):
        self._internal_hal = internal_hal

    def get_value(self, pin_name: str) -> Any:
        """Mimics hal.get_value('pin_name')."""
        return self._internal_hal.get_pin(pin_name)

    def get_p(self, pin_name: str) -> Any:
        """Mimics hal.get_value('pin_name')."""
        return self.get_value(pin_name)

    def set_p(self, pin_name: str, value: Any) -> None:
        """Mimics hal.set_p('pin_name', 'value')."""
        self._internal_hal.set_pin(pin_name, value)

    def component(self, name: str):
        """Mimics hal.component('name') if your app creates userspace components."""
        return MockComponent(name, self._internal_hal)


    @property
    def pins(self):
        """Allows direct dictionary access if tests or mappers use hal.pins['name']."""
        return self._internal_hal.pins