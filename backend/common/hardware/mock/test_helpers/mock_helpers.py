"""Test shortcuts into the mock: seed a value without waiting for the
simulated physics, inject errors, force a state."""
from typing import Any, Optional

from hardware.mock.LinuxCNCMock import mock_system
from hardware.mock.seed import reseed_from_hardware_json, reseed_mock_from_json
from hardware.mock.tools.MockHeater import MockHeater
from hardware.mock.tools.MockSpindleDigital import MockSpindleDigital

_hal = mock_system.internal_hal
_state = mock_system.internal_state


# -- HAL (the Muscle) ---------------------------------------------------------- #

def seed_temperature(sensor_id: str, actual: float, target: float = 0.0, heater_id: Optional[str] = None) -> None:
    """A heater at ``actual`` °C with ``target`` set, no ramp.

    The reading lives on the *sensor's* pin (``webgui.<sensor_id>``),
    as ``HeaterMapper`` reads it; ``heater_id`` (default: the sensor)
    names the heater's own ``target-temperature<suffix>`` pin.
    """
    heater = MockHeater(heater_id or sensor_id, sensor_id=sensor_id)
    heater.actual, heater.target = float(actual), float(target)
    _hal.register_component(heater)


def seed_spindle(spindle_id: str, actual_rpm: float, is_connected: bool = True, error_count: int = 0) -> None:
    """A spindle already at ``actual_rpm`` (no spool-up)."""
    spindle = MockSpindleDigital(spindle_id)
    spindle.actual_rpm = spindle.target_rpm = float(actual_rpm)
    spindle.spindle_at_speed = actual_rpm > 0
    spindle.is_connected = is_connected
    spindle.error_count = error_count
    _hal.register_component(spindle)


def seed_spindle_actual(spindle_id: str, actual: float, is_connected: bool = True, error_count: int = 0) -> None:
    """:func:`seed_spindle` under its older keyword (``actual``)."""
    seed_spindle(spindle_id, actual_rpm=actual, is_connected=is_connected, error_count=error_count)


def force_hal_pin(pin_name: str, value: Any) -> None:
    """Write any HAL pin (``webgui.fan_part`` …)."""
    _hal.set_pin(pin_name, value)


# -- NML state (the Brain) ------------------------------------------------------ #

def set_mock_task_state(state: int) -> None:
    """Force a task state (``STATE_ESTOP`` also sets the E-stop bit)."""
    _state.task_state = state
    if state == _state.STATE_ESTOP:
        _state.estop = 1


def set_mock_program_file(filepath: str, total_lines: int = 100) -> None:
    """Act as if ``filepath`` with ``total_lines`` lines were loaded."""
    _state.load_file(filepath, total_lines)


def reset_program_state() -> None:
    """Stop and unload the program."""
    _state.unload_program()


def reset_error_history() -> None:
    _state.clear_errors()


def push_mock_error(text: str, kind: int = 11, time: Optional[str] = None) -> None:
    """Inject an error into the LinuxCNC error channel."""
    _state.push_error(text=text, kind=kind, time=time)


def reset_simulator_state() -> None:
    """Back to an empty default machine: no tools, no stored pins."""
    mock_system.register_hardware({})
    _hal.clear_pins()


__all__ = [
    "force_hal_pin",
    "push_mock_error",
    "reseed_from_hardware_json",
    "reseed_mock_from_json",
    "reset_error_history",
    "reset_program_state",
    "reset_simulator_state",
    "seed_spindle",
    "seed_spindle_actual",
    "seed_temperature",
    "set_mock_program_file",
]
