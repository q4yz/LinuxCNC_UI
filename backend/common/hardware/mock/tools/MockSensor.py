from typing import Optional, Any

from hardware.mock.tools.MockComponent import MockComponent


class MockSensor(MockComponent):
    """A passive temperature sensor (e.g., chamber temp) with no heating element."""

    def __init__(self, sensor_id: str):
        self.id = sensor_id

        self.actual = 25.0

        # ``webgui.<sensor_id>`` — the name TemperatureSensorMapper
        # reads. Only registered for sensors NO tool references; a
        # heater's own sensor is published by that heater's MockHeater,
        # which owns the ramp physics (see LinuxCNCMock.register_hardware).
        self._pin_map = {
            f"webgui.{self.id}": "actual",
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
        """A passive sensor does not change its own temperature over time."""
        pass

    def get_legacy_state(self) -> dict[str, Any]:
        return {"actual": self.actual}