import json
import logging
from pathlib import Path
from typing import Any, Optional

from hardware.mock.LinuxCNCMock import hal, mock_system
from hardware.mock.tools.MockHeater import MockHeater
from hardware.mock.tools.MockSpindleDigital import MockSpindleDigital



# ===========================================================================
# 1. HARDWARE & HAL HELPERS (The Muscle)
# ===========================================================================
logger = logging.getLogger(__name__)

def reseed_from_hardware_json(path: "Path | None" = None) -> None:
    """Reseed the mock from the project's ``hardware.json``.

    Accepts an optional ``path`` argument:

    * ``None`` (default) — resolve the persisted default machine's
      ``machine_config/machines/<name>/config/hardware.json`` (there
      is no more ``machine_config/active/``; see
      :func:`domain_file_services.paths.default_machine_hardware_json`).
    * A directory — look up ``hardware.json`` inside it.
    * A file — use it directly.

    Missing files are logged but never raise so a stale checkout
    doesn't break tests that don't depend on the config.
    """
    if path is None:
        from domain_file_services.paths import default_machine_hardware_json

        path = default_machine_hardware_json()
    elif path.is_dir():
        path = path / "hardware.json"

    try:
        reseed_mock_from_json(path)
    except FileNotFoundError as e:
        logger.warning(str(e))

def reseed_mock_from_json(json_path: Path) -> None:
    """Rebuilds the mock hardware components from a specific hardware.json file."""
    if not json_path.exists():
        raise FileNotFoundError(f"Cannot reseed mock, file missing: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    mock_system.register_hardware(payload)


def seed_temperature(
    sensor_id: str,
    actual: float,
    target: float = 0.0,
    heater_id: "str | None" = None,
) -> None:
    """Instantly forces a temperature into the HAL pins (bypassing the slow ramp-up).

    ``sensor_id`` is the *sensor* — the reading is published on
    ``webgui.<sensor_id>``, which is what both the heater and the
    sensor entity read (see ``HeaterMapper``). Pass ``heater_id`` when
    the test also needs the heater's own ``target-temperature<suffix>``
    pin under a different name; it defaults to ``sensor_id`` so the
    historical single-tool call shape keeps working.
    """
    heater = heater_id or sensor_id
    mock_system.internal_hal.register_component(MockHeater(heater, sensor_id=sensor_id))
    suffix = heater.replace("heater", "")

    hal.set_p(sensor_id, actual)
    hal.set_p(f"target-temperature{suffix}", target)


def seed_spindle(
    spindle_id: str,
    actual_rpm: float,
    is_connected: bool = True,
    error_count: int = 0,
) -> None:
    """Instantly forces spindle telemetry into the HAL pins (bypassing slow spool-up).

    ``error_count`` is optional — defaults to ``0`` so the helper
    matches the historical single-argument call shape. Tests that
    want to exercise the error-channel broadcast pass a non-zero
    value.
    """

    mock_system.internal_hal.register_component(MockSpindleDigital(spindle_id))
    suffix = spindle_id.replace("spindle_digital", "")

    hal.set_p(f"rpm-out{suffix}", actual_rpm)
    hal.set_p(f"spindle-at-speed{suffix}", actual_rpm > 0)
    hal.set_p(f"is-connected{suffix}", is_connected)
    hal.set_p(f"error-count{suffix}", error_count)


def seed_spindle_actual(
    spindle_id: str,
    actual: float,
    is_connected: bool = True,
    error_count: int = 0,
) -> None:
    """Legacy alias for :func:`seed_spindle` with the older kwarg name.

    The pre-consolidation codebase called this helper from the
    ``hardware.linuxcnc_mock`` module; the consolidation moved it
    here. Tests still expecting the historical signature keep
    working — ``actual`` is mapped to ``actual_rpm``.
    """
    seed_spindle(
        spindle_id,
        actual_rpm=actual,
        is_connected=is_connected,
        error_count=error_count,
    )


def force_hal_pin(pin_name: str, value: Any) -> None:
    """Generic cheat code to force any HAL pin to a specific value."""
    mock_system.internal_hal.set_pin(pin_name, value)


# ===========================================================================
# 2. STATE & NML HELPERS (The Brain)
# ===========================================================================

def set_mock_task_state(state: int) -> None:
    """Forces the machine into a specific task state (e.g., STATE_ESTOP)."""
    # Directly update the Brain
    mock_system.internal_state.task_state = state
    if state == mock_system.internal_state.STATE_ESTOP:
        mock_system.internal_state.estop = 1


def set_mock_program_file(filepath: str, total_lines: int = 100) -> None:
    """Forces the mock to act as if a G-code file is loaded."""
    mock_system.internal_state.load_file(filepath, total_lines)


def reset_program_state() -> None:
    """Clears the loaded program and stops playback."""
    mock_system.internal_state.reset_program_state()


def reset_error_history() -> None:
    """Clears all simulated LinuxCNC errors."""
    mock_system.internal_state.clear_errors()


def push_mock_error(text: str, kind: int = 11, time: Optional[str] = None) -> None:
    """Injects a fake error into the LinuxCNC error channel."""
    mock_system.internal_state.push_error(text=text, kind=kind, time=time)


def reset_simulator_state():
    """Reset the orchestrator and load fresh spindles before each test."""
    mock_system.internal_hal._components.clear()
