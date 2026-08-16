from typing import Optional, Any

from hardware.mock.mock_component import MockComponent


class MockExtruder(MockComponent):
    def __init__(self, tool_id: str):
        self.tool_id = tool_id
        self.position = 0.0
        self.is_relative = False

    def read_pin(self, pin_name: str) -> Optional[Any]:
        # Expose the extruder's position as a HAL pin
        if pin_name == f"{self.tool_id}.position":
            return self.position
        return None

    def execute_gcode(self, gcode: str) -> bool:
        """Parses G1 E... and handles G90/G91 modal states."""
        cmd = gcode.upper()
        parts = cmd.split()

        handled = False
        is_move = False

        # Mini state-machine to evaluate the line left-to-right
        # (e.g. "G91 G1 E10 F300 G90")
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
        return {"position": self.position}