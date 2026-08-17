from typing import Optional, Any

from hardware.mock.tools.mock_component import MockComponent
from hardware.mock.tools.mock_heater import MockHeater


class MockExtruder(MockComponent):
    def __init__(self, tool_id: str):
        self.id = tool_id
        self.position = 0.0
        self.is_relative = False

        # The hidden hotend!
        # It perfectly reuses all the heating/cooling physics we already wrote.
        self._heater = MockHeater(tool_id)

    def read_pin(self, pin_name: str) -> Optional[Any]:
        # 1. Check if it's an extruder-specific pin
        if pin_name == f"{self.id}.position":
            return self.position

        # 2. If not, ask the hidden heater (e.g. actual-temperature-extruder)
        return self._heater.read_pin(pin_name)

    def set_pin(self, pin_name: str, value: Any) -> bool:
        # Delegate pin setting (like target-temperature) directly to the heater
        return self._heater.set_pin(pin_name, value)

    def update(self, hal, nml, delta_time: float) -> None:
        # Tick the hidden heater's physics loop so it ramps up/down
        self._heater.update(hal, nml, delta_time)

    def execute_mdi(self, gcode: str) -> bool:
        """Parses G1 E... and handles G90/G91 modal states."""
        cmd = gcode.upper()
        parts = cmd.split()

        handled = False
        is_move = False

        # Mini state-machine to evaluate the line left-to-right
        for part in parts:
            if part == "G90":
                self.is_relative = False
                handled = True
            elif part == "G91":
                self.is_relative = True
                handled = True
            elif part in ("G0", "G1"):
                is_move = True
                handled = True
            elif part.startswith("E") and is_move:
                val = float(part[1:])
                if self.is_relative:
                    self.position += val
                else:
                    self.position = val
                handled = True

        return handled

    def get_legacy_state(self) -> dict:
        # Combine the states for legacy UI support
        state = {"position": self.position}
        state.update(self._heater.get_legacy_state())
        return state