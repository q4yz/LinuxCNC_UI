

_PROJECT_ROOT = None

def _get_project_root():
    global _PROJECT_ROOT
    if _PROJECT_ROOT is None:
        from pathlib import Path
        _PROJECT_ROOT = Path(__file__).resolve().parents[1]
    return _PROJECT_ROOT

def _default_hardware_paths():
    root = _get_project_root()
    return [
        root / "machine_config" / "active" / "hardware.json",
        root / "machine_config" / "ready_for_deploy" / "hardware.json",
    ]

# --- LinuxCNC Constants ---
STATE_ESTOP, STATE_ESTOP_RESET, STATE_OFF, STATE_ON = 1, 2, 3, 4
MODE_MANUAL, MODE_AUTO, MODE_MDI = 1, 2, 3
RCS_DONE, RCS_EXEC, RCS_ERROR = 1, 2, 3
JOG_STOP, JOG_CONTINUOUS, JOG_INCREMENT = 0, 1, 2
AUTO_RUN, AUTO_PAUSE, AUTO_RESUME, AUTO_STEP = 0, 1, 2, 3
INTERP_IDLE, INTERP_READING, INTERP_PAUSED, INTERP_WAITING = 1, 2, 3, 4
NML_ERROR, OPERATOR_ERROR, OPERATOR_TEXT, OPERATOR_DISPLAY = 1, 2, 3, 4

TRAJ_MODE_FREE = 1
TRAJ_MODE_TELEOP = 3
