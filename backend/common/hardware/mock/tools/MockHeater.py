from typing import Optional

from hardware.mock.tools.MockComponent import MockComponent

#: Room temperature the heaters cool down to (°C).
AMBIENT = 25.0


class MockHeater(MockComponent):
    """A heater with its sensor: heats towards the target, cools to room
    temperature.

    Like the generated HAL (``heat-ok-<id>``: board link AND not in
    E-stop), it only heats while the machine is out of E-stop, and the
    target is capped at the configured ``max_temp`` (the PID's SPmax).
    The reading is published on the *sensor's* pin (``webgui.<sensor>``),
    the one ``HeaterMapper`` reads; a sensor-less heater keeps the
    derived ``actual-temperature<suffix>`` name.
    """

    _pin_cast = float
    HEAT_RATE = 2.0  # °C/s
    COOL_RATE = 0.5  # °C/s

    def __init__(self, id: str, sensor_id: Optional[str] = None, max_temp: Optional[float] = None):
        self.id = id
        self.actual = AMBIENT
        self.target = 0.0
        self.max_temp = max_temp
        suffix = self.id.replace("heater", "")
        actual_pin = sensor_id if sensor_id else f"actual-temperature{suffix}"
        self._pin_map = {
            f"webgui.{actual_pin}": "actual",
            f"webgui.target-temperature{suffix}": "target",
        }

    @property
    def effective_target(self) -> float:
        return self.target if self.max_temp is None else min(self.target, self.max_temp)

    def update(self, hal, nml, delta_time: float) -> None:
        target = 0.0 if getattr(nml, "estop", 0) else self.effective_target
        if target > self.actual:
            self.actual = min(target, self.actual + self.HEAT_RATE * delta_time)
        elif self.actual > AMBIENT:
            self.actual = max(max(target, AMBIENT), self.actual - self.COOL_RATE * delta_time)
