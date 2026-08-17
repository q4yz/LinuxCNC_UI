from typing import Optional, Any
from hardware.mock.tools.mock_component import MockComponent

class MockSpindleDigital(MockComponent):
    def __init__(self, tool_id: str):
        self.id = tool_id

        # Internal State is owned EXCLUSIVELY by this component!
        self.actual_rpm = 0.0
        self.target_rpm = 0.0
        self.is_connected = False
        self.error_count = 0
        self.last_error = ""
        self.spindle_forward = False
        self.spindle_reverse = False
        self.spindle_at_speed = False
        self.override = 1.0

        # Calculate the suffix exactly as the ConfigMapper does
        suffix = self.id.replace("spindle_digital", "")

        # Exact dictionary mapping of HAL pin strings to internal state attributes
        self._pin_map = {
            f"rpm-out{suffix}": "actual_rpm",
            f"TargetRpm{suffix}": "target_rpm",
            f"spindle-forward{suffix}": "spindle_forward",
            f"spindle-reverse{suffix}": "spindle_reverse",
            f"spindle-at-speed{suffix}": "spindle_at_speed",
            f"is-connected{suffix}": "is_connected",
            f"error-count{suffix}": "error_count",
            f"last-error{suffix}": "last_error",
            f"override{suffix}": "override",
        }

    def read_pin(self, pin_name: str) -> Optional[Any]:
        """Strictly look up the pin name in the dictionary."""
        if pin_name in self._pin_map:
            attr_name = self._pin_map[pin_name]
            return getattr(self, attr_name)
        return None

    def set_pin(self, pin_name: str, value: Any) -> bool:
        """Allow setting pins directly (e.g., if you command an override change)."""
        if pin_name in self._pin_map:
            attr_name = self._pin_map[pin_name]
            setattr(self, attr_name, value)
            return True
        return False

    def execute_mdi(self, gcode: str) -> bool:
        """Parse SpindleDigital M-codes and set the internal target states."""
        cmd = gcode.upper()

        if cmd.startswith("M3") or cmd.startswith("M4"):
            parts = cmd.split()
            speed = next((float(p[1:]) for p in parts if p.startswith("S")), 1000.0)

            self.is_connected = True
            self.target_rpm = speed

            if cmd.startswith("M3"):
                self.spindle_forward = True
                self.spindle_reverse = False
            else:
                self.spindle_forward = False
                self.spindle_reverse = True
            return True

        elif cmd.startswith("M5"):
            self.is_connected = False
            self.target_rpm = 0.0
            self.spindle_forward = False
            self.spindle_reverse = False
            return True

        return False

    def update(self, hal, nml, delta_time: float) -> None:
        """Simulate VFD physics: Spooling up and down."""
        # Ramp RPM up or down by 5000 RPM per second
        ramp_rate = 5000.0 * delta_time

        if self.actual_rpm < self.target_rpm:
            self.actual_rpm = min(self.target_rpm, self.actual_rpm + ramp_rate)
        elif self.actual_rpm > self.target_rpm:
            self.actual_rpm = max(self.target_rpm, self.actual_rpm - ramp_rate)

        # SpindleDigital-at-speed is True when running and within 5% of target RPM
        if self.target_rpm > 0 and abs(self.actual_rpm - self.target_rpm) <= (self.target_rpm * 0.05):
            self.spindle_at_speed = True
        else:
            self.spindle_at_speed = False

    def get_legacy_state(self) -> dict:
        """Used if old UI components still query the stat channel directly."""
        return {
            "target_rpm": self.target_rpm,
            "actual": self.actual_rpm,
            "actual_rpm": self.actual_rpm,
            "is_connected": self.is_connected,
            "error_count": self.error_count,
            "last_error": self.last_error,
            "spindle_forward": self.spindle_forward,
            "spindle_reverse": self.spindle_reverse,
            "spindle_at_speed": self.spindle_at_speed,
            "override": self.override
        }