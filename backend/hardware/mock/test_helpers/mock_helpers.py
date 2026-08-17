import json
import logging
from pathlib import Path
from typing import Any

from hardware.mock.linuxcnc_mock import hal, mock_system
from hardware.mock.tools.mock_heater import MockHeater
from hardware.mock.tools.mock_spindle_digital import MockSpindleDigital



# ===========================================================================
# 1. HARDWARE & HAL HELPERS (The Muscle)
# ===========================================================================
logger = logging.getLogger(__name__)

def reseed_from_hardware_json() -> None:
    project_root = Path(__file__).resolve().parents[4]
    hw_path = project_root / "machine_config" / "active" / "hardware.json"

    try:
        reseed_mock_from_json(hw_path)
    except FileNotFoundError as e:
        logger.warning(str(e))

def reseed_mock_from_json(json_path: Path) -> None:
    """Rebuilds the mock hardware components from a specific hardware.json file."""
    if not json_path.exists():
        raise FileNotFoundError(f"Cannot reseed mock, file missing: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    mock_system.register_hardware(payload)


def seed_temperature(sensor_id: str, actual: float, target: float = 0.0) -> None:
    """Instantly forces a temperature into the HAL pins (bypassing the slow ramp-up)."""

    mock_system.internal_hal.register_component(MockHeater(sensor_id))
    suffix = sensor_id.replace("heater", "")

    hal.set_p(f"actual-temperature{suffix}", actual)
    hal.set_p(f"target-temperature{suffix}", target)


def seed_spindle(spindle_id: str, actual_rpm: float, is_connected: bool = True) -> None:
    """Instantly forces spindle telemetry into the HAL pins (bypassing slow spool-up)."""

    mock_system.internal_hal.register_component(MockSpindleDigital(spindle_id))
    suffix = spindle_id.replace("spindle_digital", "")

    hal.set_p(f"rpm-out{suffix}", actual_rpm)
    hal.set_p(f"spindle-at-speed{suffix}", actual_rpm > 0)
    hal.set_p(f"is-connected{suffix}", is_connected)


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


def push_mock_error(text: str, kind: int = 11, time: str = None) -> None:
    """Injects a fake error into the LinuxCNC error channel."""
    mock_system.internal_state.push_error(text=text, kind=kind, time=time)


def reset_simulator_state():
    """Reset the orchestrator and load fresh spindles before each test."""
    mock_system.internal_hal._components.clear()
