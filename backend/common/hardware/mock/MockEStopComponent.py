"""Mock HAL component for the critical E-Stop pin.

Always loaded by ``LinuxCNCMock.__init__`` — unlike the per-tool
mock components (heater / spindle / sensor / extruder) which are
registered from ``payload["tools"]`` at reseed time, the E-Stop
component exists from the moment the mock system is constructed.

Mirrors the real HAL file: ``webgui.estop`` (Python-driven) is
wired in ``custom.hal`` to ``halui.estop.activate``, which
edge-detects a 0 -> 1 transition and calls
``task.set_state(STATE_ESTOP)``. The mock short-circuits that
wire: when ``webgui.estop`` is written with any truthy value, we
call ``StateMachineMock.trigger_estop()`` directly so the same
Python write produces the same observable state change (estop bit,
task_state = STATE_ESTOP, interp_state = IDLE).

The 0 -> 1 dance that ``EStopPin`` performs before calling
``set_value(True)`` is preserved in the wrapper, so a fresh press
after a reset cycle always lands a 1 on the pin. Edge detection
itself is not modelled here — see ``MOCK_ARCHITECTURE.md`` for the
rationale (the trade-off is simpler reasoning vs. faithful
replication of halui's rising-edge semantics).
"""
from typing import Any, Optional

from hardware.mock.tools.MockComponent import MockComponent


class MockEStopComponent(MockComponent):
    """Trigger-on-truthy mock for the ``webgui.estop`` pin.

    Subscribes to ``webgui.estop`` exclusively. Any other pin name
    is ignored (returns ``False`` from ``set_pin``) so unrelated
    writes don't accidentally engage the E-Stop.
    """

    PIN_NAME = "webgui.estop"
    COMPONENT_ID = "estop"

    def __init__(self, state_machine):
        # ``HalMock.register_component`` dedups by ``getattr(c, 'id')``;
        # every always-on component needs a stable id.
        self.id = self.COMPONENT_ID
        self._state_machine = state_machine

    def read_pin(self, pin_name: str) -> Optional[Any]:
        if pin_name == self.PIN_NAME:
            return int(getattr(self._state_machine, "estop", 0))
        return None

    def set_pin(self, pin_name: str, value: Any) -> bool:
        if pin_name != self.PIN_NAME:
            return False
        if value:
            self._state_machine.trigger_estop()
        return True

    def update(self, hal, nml, delta_time: float) -> None:
        # No physics — the state machine owns the ESTOP lifecycle.
        # Calling ``trigger_estop`` on a 1-write is enough; the
        # tick loop has nothing to integrate.
        pass
