"""The HAL identity of a temperature sensor is its id, not its wiring.

``hardware.json`` carries two different kinds of "pin" for a sensor and
they must not be confused:

* ``temperature_sensors[].id`` — the logical sensor. This is what the
  webgui component exposes as a HAL pin (``webgui.<id>``) and what a
  machine's HAL file wires against.
* ``temperature_sensors[].pin`` — the *MCU* pin the thermistor is
  physically attached to (``"PA1"``), written by
  ``hardware_json_generator._temperature_sensor_payload`` from the
  Klipper profile's ``sensor_pin``. It is routing data for the HAL
  compiler, which connects ``webgui.<id>`` to ``<mcu>.PA1``.

The mapper used to fall back to reading ``pin`` as the HAL pin name,
producing pins literally called ``webgui.PA1`` — a name no generated
machine.hal could meaningfully wire, and one that changes whenever the
operator re-plugs the thermistor. These tests pin the separation.
"""

from mappers.temperature.TemperatureSensorMapper import TemperatureSensorMapper


def _pin_name(data: dict) -> str:
    return TemperatureSensorMapper.from_dict_to_TemperaturePins(data).actual_temperature.get_pin_name()


def test_hal_pin_is_named_after_the_sensor_id():
    assert _pin_name({"id": "extruder_test", "pin": "PA1"}) == "extruder_test"
    assert _pin_name({"id": "bed", "pin": "PA0"}) == "bed"


def test_mcu_pin_never_leaks_into_the_hal_pin_name():
    """The regression: ``pin`` is wiring, not identity."""
    for mcu_pin in ("PA1", "^PC0", "!PE3", "par0:02"):
        assert _pin_name({"id": "bed", "pin": mcu_pin}) == "bed"


def test_pin_field_is_optional():
    """A sensor with no MCU pin yet is still addressable in HAL."""
    assert _pin_name({"id": "chamber"}) == "chamber"


def test_id_is_preserved_on_the_dto():
    pins = TemperatureSensorMapper.from_dict_to_TemperaturePins({"id": "bed", "pin": "PA0"})
    assert pins.id == "bed"
