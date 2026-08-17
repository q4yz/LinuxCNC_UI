from typing import Optional, Any
from hardware.mock.tools.mock_component import MockComponent

class MockHeater(MockComponent):
    def __init__(self, tool_id: str):
        self.id = tool_id

        # Internal State
        self.actual = 25.0
        self.target = 0.0

        # Calculate the suffix exactly as the ConfigMapper expects
        suffix = self.id.replace("heater", "")

        # Exact dictionary mapping of HAL pin strings to internal state attributes
        self._pin_map = {
            f"actual-temperature{suffix}": "actual",
            f"target-temperature{suffix}": "target",
        }

    def read_pin(self, pin_name: str) -> Optional[Any]:
        if pin_name in self._pin_map:
            attr_name = self._pin_map[pin_name]
            return getattr(self, attr_name)
        return None

    def set_pin(self, pin_name: str, value: Any) -> bool:
        if pin_name in self._pin_map:
            attr_name = self._pin_map[pin_name]
            setattr(self, attr_name, float(value))
            return True
        return False

    def update(self, hal, nml, delta_time: float) -> None:
        """Simulate active heating up and cooling down."""
        ambient = 25.0

        if self.target > self.actual:
            # Heat up by 2 degrees per second
            self.actual = min(self.target, self.actual + (2.0 * delta_time))
        elif self.actual > ambient and self.target < self.actual:
            # Cool down by 0.5 degrees per second
            self.actual = max(ambient, self.actual - (0.5 * delta_time))

    def get_legacy_state(self) -> dict:
        return {"actual": self.actual, "target": self.target}