from hardware.mock.tools.MockComponent import MockComponent
from hardware.mock.tools.MockHeater import AMBIENT


class MockSensor(MockComponent):
    """A passive temperature sensor (a chamber probe): no heater drives it.

    Publishes ``webgui.<sensor_id>`` (what ``TemperatureSensorMapper``
    reads). Registered only for sensors no tool references; a heater's
    own sensor is published by its :class:`MockHeater`.
    """

    _pin_cast = float

    def __init__(self, sensor_id: str):
        self.id = sensor_id
        self.actual = AMBIENT
        self._pin_map = {f"webgui.{self.id}": "actual"}
