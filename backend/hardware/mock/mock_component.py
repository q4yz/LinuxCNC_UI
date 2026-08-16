from typing import Any, Optional


class MockComponent:
    """Base class for all mock hardware components."""

    def read_pin(self, pin_name: str) -> Optional[Any]:
        """Return the pin value if this component owns it, else None."""
        return None

    def set_pin(self, pin_name: str, value: Any) -> bool:
        """Set a pin value. Return True if this component handled it."""
        return False

    def execute_gcode(self, gcode: str) -> bool:
        """Parse G-code (like M3, G1 E). Return True if handled."""
        return False

    def update(self, delta_time: float) -> None:
        """Simulate physics for this tick (e.g., heating up, accelerating)."""
        pass