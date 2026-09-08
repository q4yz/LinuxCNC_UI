"""A heater carries a sensor — it does not own a second copy of the reading.

One thermistor is one HAL pin, ``webgui.<sensor_id>``, addressed the
same way whether or not a heater claims it:

* ``HeaterMapper`` names ``actual_temperature`` after the heater's
  ``sensor`` reference, not after its own id.
* ``TemperatureSensorMapper`` names its pin after the sensor id.
* The mock publishes on that same pin, so mock mode reads real values.

Before this, the heater published ``actual-temperature<suffix>`` while
the sensor entity was skipped by the service dedup — so a reading was
addressed differently depending on who claimed it, and the mock used a
third spelling again (``actual-temperature-<id>``) that matched
neither, leaving mock sensor reads dead.

The service-layer dedup that makes the pairing safe lives in
``TemperatureService.preload_hal_pins`` and ``pin_catalog``: a sensor a
heater claims is never built as a separate entity, so the shared name
can never double-register.
"""

from hardware.mock.factory.MockToolFactory import MockToolFactory
from hardware.mock.tools.MockSensor import MockSensor
from mappers.temperature.TemperatureSensorMapper import TemperatureSensorMapper
from mappers.tools.HeaterMapper import HeaterMapper


def _heater_actual(data: dict) -> str:
    return HeaterMapper.from_dict_to_HeaterPins(data).actual_temperature.get_pin_name()


def test_heater_reads_its_sensors_pin():
    data = {"id": "heater_bed", "sensor": "bed", "min_temp": 0.0, "max_temp": 130.0}
    assert _heater_actual(data) == "bed"


def test_heater_setpoint_stays_heater_owned():
    """The setpoint belongs to the heater; only the reading is the sensor's."""
    pins = HeaterMapper.from_dict_to_HeaterPins({"id": "heater_bed", "sensor": "bed"})
    assert pins.target_temperature.get_pin_name() == "target-temperature_bed"


def test_heater_and_sensor_resolve_to_the_same_pin():
    heater = {"id": "heater_bed", "sensor": "bed"}
    sensor = {"id": "bed", "pin": "PA0"}

    heater_pin = HeaterMapper.from_dict_to_HeaterPins(heater).actual_temperature.get_pin_name()
    sensor_pin = TemperatureSensorMapper.from_dict_to_TemperaturePins(sensor).actual_temperature.get_pin_name()

    assert heater_pin == sensor_pin == "bed"


def test_sensorless_heater_keeps_the_derived_name():
    """Configs with no sensor reference must keep working."""
    assert _heater_actual({"id": "heater_bed"}) == "actual-temperature_bed"


def test_mock_heater_publishes_on_the_pin_the_mapper_reads():
    """The regression that made mock mode read dead pins.

    The mock and the mapper derived the HAL name independently and
    drifted apart. Assert they agree, for a heater and an extruder.
    """
    for record in (
        {"id": "heater_bed", "type": "heated_bed", "sensor": "bed"},
        {"id": "heater_extruder_test", "type": "extruder", "sensor": "extruder_test"},
    ):
        expected = f"webgui.{_heater_actual(record)}"
        mock = MockToolFactory.create(record)
        assert mock is not None, record["id"]
        # MockExtruder delegates its pin map to the hidden hotend.
        assert mock.read_pin(expected) is not None, (
            f"{type(mock).__name__} does not publish {expected}"
        )


def test_mock_sensor_publishes_on_the_pin_the_mapper_reads():
    sensor = {"id": "chamber", "pin": "PA5"}
    expected = "webgui." + TemperatureSensorMapper.from_dict_to_TemperaturePins(
        sensor
    ).actual_temperature.get_pin_name()

    assert MockSensor("chamber").read_pin(expected) is not None
