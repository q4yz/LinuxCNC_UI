import logging
import threading
import time

from hardware.mock.factory.mock_tool_factory import MockToolFactory
from hardware.mock.hal_mock import HalMock
from hardware.mock.hal_module_facade import HalModuleFacade
from hardware.mock.linuxcnc_module_facade import LinuxcncModuleFacade
from hardware.mock.state_machine_mock import StateMachineMock

logger = logging.getLogger("backend.hardware.mock")


class LinuxCNCMock:
    def __init__(self):

        self.internal_state: StateMachineMock = StateMachineMock()
        self.internal_hal: HalMock = HalMock(nml_state=self.internal_state)
        self.hal: HalModuleFacade = HalModuleFacade(internal_hal=self.internal_hal)
        self.linuxcnc: LinuxcncModuleFacade = LinuxcncModuleFacade(state_mock=self.internal_state,hal_mock=self.internal_hal)

        self._running = False
        self._thread = None
        self._PROJECT_ROOT = None

    def start_simulation(self):
        """Starts the background heartbeat thread."""
        self._running = True
        self._thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._thread.start()

    def _tick_loop(self):
        """The main simulation loop (like the LinuxCNC servo thread)."""
        while self._running:
            self.internal_hal.update()
            self.internal_state.update(self.hal)
            time.sleep(0.1)

    def register_hardware(self, payload: dict):
        """Parses a hardware.json payload and registers the active components."""

        for tool_record in payload.get("tools", []):
            if not isinstance(tool_record, dict):
                continue

            # Let the factory decide which OOP class to build
            mock_component = MockToolFactory.create(tool_record)

            # If the factory built one, plug it into the tick loop!
            if mock_component:
                self.internal_hal.register_component(mock_component)
                logger.debug("Registered mock component for %s", tool_record.get("id"))


mock_system = LinuxCNCMock()

hal = mock_system.hal
linuxcnc = mock_system.linuxcnc
