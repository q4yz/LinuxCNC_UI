import logging
import threading
import time
from typing import Any, Optional

from hardware.mock.config import MockMachineConfig
from hardware.mock.factory.MockToolFactory import MockToolFactory
from hardware.mock.HalMock import HalMock
from hardware.mock.facade.HalModuleFacade import HalModuleFacade
from hardware.mock.facade.LinuxcncModuleFacade import LinuxcncModuleFacade
from hardware.mock.MockDebugSignals import MockDebugSignals
from hardware.mock.MockEStopComponent import MockEStopComponent
from hardware.mock.StateMachineMock import StateMachineMock
from hardware.mock.tools.MockSensor import MockSensor

logger = logging.getLogger("backend.hardware.mock")

#: Tick period of the simulation thread (s) — like a slow servo thread.
TICK = 0.1


class LinuxCNCMock:
    """Wires the mock together: the state machine (``linuxcnc.stat``),
    the HAL pins and their components, the ``hal`` / ``linuxcnc``
    facades, and the tick thread.

    :meth:`register_hardware` shapes it after a machine's
    ``hardware.json``: axes, joints and travel go to the state machine,
    each tool and free sensor becomes a component. Calling it again
    (another machine) replaces the previous machine's components; the
    always-on ones (E-stop, debug signals) stay.
    """

    def __init__(self) -> None:
        self.config: MockMachineConfig = MockMachineConfig.default()
        self.internal_state: StateMachineMock = StateMachineMock(self.config)
        self.internal_hal: HalMock = HalMock(nml_state=self.internal_state)
        self.hal: HalModuleFacade = HalModuleFacade(internal_hal=self.internal_hal)
        self.linuxcnc: LinuxcncModuleFacade = LinuxcncModuleFacade(state_mock=self.internal_state, hal_mock=self.internal_hal)

        # Always on: services rely on these pins at any tick, whether or
        # not a hardware.json has been registered yet.
        self._always_on = (MockEStopComponent(self.internal_state), MockDebugSignals())
        for component in self._always_on:
            self.internal_hal.register_component(component)

        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start_simulation(self):
        """Start the tick thread (once)."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._tick_loop, daemon=True, name="linuxcnc-mock")
        self._thread.start()

    def stop_simulation(self):
        self._running = False

    def tick(self, delta_time: float = TICK) -> None:
        """One simulation step (the thread calls it; tests can too)."""
        self.internal_hal.update(delta_time)
        self.internal_state.update(self.internal_hal, delta_time)

    def _tick_loop(self):
        while self._running:
            self.tick(TICK)
            time.sleep(TICK)

    def register_hardware(self, payload: dict[str, Any]):
        """Simulate the machine ``payload`` (a ``hardware.json``) describes."""
        payload = payload or {}
        self.config = MockMachineConfig.from_payload(payload)
        self.internal_state.configure(self.config)
        always_on = {id(c) for c in self._always_on}
        self.internal_hal.remove_components(lambda c: id(c) not in always_on)

        claimed_sensors: set[str] = set()
        for tool_record in payload.get("tools") or []:
            if not isinstance(tool_record, dict):
                continue
            component = MockToolFactory.create(tool_record, self.config.heaters.get(str(tool_record.get("id"))))
            if component is None:
                continue
            self.internal_hal.register_component(component)
            # A heater publishes its own sensor's reading (it owns the
            # ramp), so that sensor gets no passive MockSensor: two
            # components answering one pin would shadow the ramp.
            if tool_record.get("sensor"):
                claimed_sensors.add(str(tool_record["sensor"]))

        for sensor_record in payload.get("temperature_sensors") or []:
            sensor_id = sensor_record.get("id") if isinstance(sensor_record, dict) else None
            if sensor_id and str(sensor_id) not in claimed_sensors:
                self.internal_hal.register_component(MockSensor(str(sensor_id)))
        logger.info(
            "Mock machine: axes %s, %d joints, %d components",
            "".join(a.letter.upper() for a in self.config.axes),
            self.config.joint_count,
            len(self.internal_hal.components),
        )


mock_system = LinuxCNCMock()

hal = mock_system.hal
linuxcnc = mock_system.linuxcnc
