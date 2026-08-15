import time
import threading
import logging
from typing import Any, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("linuxcnc_mock")

# Module-level path resolution so tests can monkey-patch the
# ``hardware.json`` location the seeders read from.
_PROJECT_ROOT = None


def _get_project_root():
    """Resolve the repo root lazily so ``monkeypatch.setattr`` can
    replace it before the first seeder call.
    """
    global _PROJECT_ROOT
    if _PROJECT_ROOT is None:
        from pathlib import Path
        _PROJECT_ROOT = Path(__file__).resolve().parents[1]
    return _PROJECT_ROOT


def _default_hardware_paths():
    """Return the default ``hardware.json`` locations to probe."""
    root = _get_project_root()
    return [
        root / "machine_config" / "active" / "hardware.json",
        root / "machine_config" / "ready_for_deploy" / "hardware.json",
    ]


# --- LinuxCNC Constants ---
STATE_ESTOP = 1
STATE_ESTOP_RESET = 2
STATE_OFF = 3
STATE_ON = 4

MODE_MANUAL = 1
MODE_AUTO = 2
MODE_MDI = 3

RCS_DONE = 1
RCS_EXEC = 2
RCS_ERROR = 3

# Jogging
JOG_STOP = 0
JOG_CONTINUOUS = 1
JOG_INCREMENT = 2

# Auto/Program
AUTO_RUN = 0
AUTO_PAUSE = 1
AUTO_RESUME = 2
AUTO_STEP = 3

# Interpreter
INTERP_IDLE = 1
INTERP_READING = 2
INTERP_PAUSED = 3
INTERP_WAITING = 4

# Errors
NML_ERROR = 1
OPERATOR_ERROR = 2
OPERATOR_TEXT = 3
OPERATOR_DISPLAY = 4


# --- Shared State ---
def _load_hardware_payload():
    """Read the active ``hardware.json`` once and return its dict."""
    import json

    for path in _default_hardware_paths():
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, ValueError):
            return None
        if isinstance(data, dict):
            return data
    return None


def _seed_temperatures_from_hardware():
    """Reset ``_machine_state.temperatures`` from the active ``hardware.json``.

    Automatically finds tools of type heater, heated_bed, or extruder
    and seeds them so the dashboard temperature panel works out of the box.
    """
    payload = _load_hardware_payload()
    with _machine_state.lock:
        _machine_state.temperatures = {}
        if isinstance(payload, dict) and isinstance(payload.get("tools"), list):
            for tool in payload["tools"]:
                if isinstance(tool, dict) and tool.get("type") in ("heater", "heated_bed", "extruder"):
                    sensor_name = tool.get("sensor") or tool.get("id")
                    if sensor_name:
                        _machine_state.temperatures[sensor_name] = {'actual': 25.0, 'target': 0.0}

        # Legacy backward-compatibility for single-extruder callers
        legacy_extruder = next(
            (v for k, v in _machine_state.temperatures.items() if k == 'extruder' or k.startswith('extruder')),
            None,
        )
        if legacy_extruder is not None:
            _machine_state.target_temp = legacy_extruder.get('target', 0.0)
            _machine_state.actual_temp = legacy_extruder.get('actual', 25.0)
        else:
            _machine_state.target_temp = 0.0
            _machine_state.actual_temp = 25.0


def _seed_spindle_actual_from_hardware():
    """Reset ``_machine_state.spindle_actual`` from the active ``hardware.json``."""
    payload = _load_hardware_payload()
    with _machine_state.lock:
        _machine_state.spindle_actual = {}
        if not isinstance(payload, dict):
            return
        raw_tools = payload.get("tools")
        if not isinstance(raw_tools, list):
            return
        for tool in raw_tools:
            if not isinstance(tool, dict) or tool.get("type") != "spindle_digital":
                continue
            tool_id = tool.get("id")
            if isinstance(tool_id, str) and tool_id:
                _machine_state.spindle_actual[tool_id] = {
                    "actual": 0,
                    "is_connected": False,
                    "error_count": 0,
                }


class SharedMachineState:
    def __init__(self):
        self.task_state = STATE_ESTOP
        self.estop = 1
        self.task_mode = MODE_MANUAL
        self.position = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.actual_position = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.state = 1
        self.file = ""
        self.homed = [0, 0, 0]
        self.interp_state = INTERP_IDLE
        self.current_line = 0
        self.total_lines = 0
        self.g5x_index = 1

        self.lock = threading.Lock()
        self.temperatures: dict = {}
        self.spindle_actual: dict = {}
        self.target_temp = 0.0
        self.actual_temp = 25.0

        self.program_thread = None
        self.program_stop_event = threading.Event()
        self.jogging_axis = None
        self.jogging_velocity = 0.0
        self.jog_thread = None
        self.jog_stop_event = threading.Event()

        self.errors: list = []
        self._max_errors = 100

    def push_error(self, kind: int, text: str, time: str) -> None:
        entry = {"kind": kind, "text": text, "time": time}
        with self.lock:
            self.errors.append(entry)
            if len(self.errors) > self._max_errors:
                del self.errors[: len(self.errors) - self._max_errors]


_machine_state = SharedMachineState()


def is_program_loaded() -> bool:
    try:
        from .connection import get_machine_stat
        stat = get_machine_stat()
    except ImportError:
        stat = None
    if stat is not None:
        poll = getattr(stat, "poll", None)
        if callable(poll):
            poll()
        return bool(getattr(stat, "file", ""))
    with _machine_state.lock:
        return bool(_machine_state.file)


def reseed_from_hardware_json():
    _seed_temperatures_from_hardware()
    _seed_spindle_actual_from_hardware()


def update_spindle_telemetry(tool_id: str, *, actual: Optional[int] = None, is_connected: Optional[bool] = None,
                             error_count: Optional[int] = None) -> None:
    if not isinstance(tool_id, str) or not tool_id:
        return
    with _machine_state.lock:
        entry = _machine_state.spindle_actual.setdefault(tool_id,
                                                         {"actual": 0, "is_connected": False, "error_count": 0})
        if actual is not None: entry["actual"] = actual
        if is_connected is not None: entry["is_connected"] = bool(is_connected)
        if error_count is not None: entry["error_count"] = error_count


def apply_spindle_pin(tool_id: str, pin_name: str, pin_value: Any) -> None:
    if not isinstance(tool_id, str) or not tool_id:
        return
    with _machine_state.lock:
        entry = _machine_state.spindle_actual.setdefault(tool_id,
                                                         {"actual": 0, "is_connected": False, "error_count": 0})
        if pin_name.endswith(("rpm-out", "rpm_out")):
            entry["actual"] = int(pin_value)
        if pin_name.endswith(("at-speed", "at_speed", "on", "forward", "reverse", "istop", "estop", "vfd-enable",
                              "vfd_enable")) and bool(pin_value):
            entry["is_connected"] = True
        if pin_name.endswith(("istop", "estop")) and pin_value:
            entry["error_count"] = int(entry.get("error_count", 0)) + 1
        if pin_name.endswith(("on", "vfd-enable", "vfd_enable")) and not pin_value:
            entry["is_connected"] = False


def record_error(kind: int, text: str, time: str) -> None:
    _machine_state.push_error(int(kind), str(text), str(time))


def push_mock_error(kind: int, text: str, time: str) -> None:
    channel = error_channel()
    channel.errors.append((int(kind), str(text), str(time)))


def seed_temperature(sensor_name: str, actual: float, target: float) -> None:
    if not isinstance(sensor_name, str) or not sensor_name:
        return
    with _machine_state.lock:
        _machine_state.temperatures[sensor_name] = {"actual": float(actual), "target": float(target)}


def seed_spindle_actual(tool_id: str, **fields: object) -> None:
    if not isinstance(tool_id, str) or not tool_id:
        return
    with _machine_state.lock:
        entry = _machine_state.spindle_actual.setdefault(tool_id,
                                                         {"actual": 0, "is_connected": False, "error_count": 0})
        for key, value in fields.items():
            entry[key] = value


def set_mock_task_state(state: int) -> None:
    with _machine_state.lock: _machine_state.task_state = int(state)


def set_mock_program_file(path: str) -> None:
    with _machine_state.lock: _machine_state.file = str(path)


def reset_program_state() -> None:
    with _machine_state.lock:
        _machine_state.file = ""
        _machine_state.current_line = 0
        _machine_state.total_lines = 0
        _machine_state.interp_state = INTERP_IDLE


def reset_error_history() -> None:
    with _machine_state.lock: _machine_state.errors.clear()


def _jog_simulation_loop():
    while not _machine_state.jog_stop_event.is_set():
        with _machine_state.lock:
            if _machine_state.jogging_axis is not None:
                delta = (_machine_state.jogging_velocity / 60.0) * 0.1
                _machine_state.position[_machine_state.jogging_axis] += delta
                _machine_state.actual_position[_machine_state.jogging_axis] += delta
        time.sleep(0.1)


def _program_simulation_loop():
    while not _machine_state.program_stop_event.is_set():
        advance = False
        with _machine_state.lock:
            if _machine_state.interp_state == INTERP_READING and _machine_state.current_line < _machine_state.total_lines:
                _machine_state.current_line += 1
                if _machine_state.current_line >= _machine_state.total_lines:
                    _machine_state.interp_state = INTERP_IDLE
                advance = True
            elif _machine_state.interp_state == INTERP_READING and _machine_state.current_line >= _machine_state.total_lines:
                _machine_state.interp_state = INTERP_IDLE
        if not advance:
            time.sleep(0.1)
            continue
        time.sleep(0.1)


def _start_program_simulation_if_needed() -> None:
    with _machine_state.lock:
        thread = _machine_state.program_thread
        if thread is not None and thread.is_alive(): return
        _machine_state.program_stop_event.clear()
        _machine_state.program_thread = threading.Thread(target=_program_simulation_loop, daemon=True)
        _machine_state.program_thread.start()


def _stop_program_simulation() -> None:
    with _machine_state.lock:
        thread = _machine_state.program_thread
        _machine_state.program_stop_event.set()
        _machine_state.program_thread = None
    if thread is not None and thread.is_alive():
        thread.join(timeout=0.5)


def _temp_simulation_loop():
    while True:
        with _machine_state.lock:
            ambient = 25.0
            for sensor_name, sensor_values in _machine_state.temperatures.items():
                actual = sensor_values.get('actual', ambient)
                if 'target' in sensor_values:
                    target = sensor_values.get('target', 0.0)
                    if target > actual:
                        sensor_values['actual'] = actual + min(1.0, target - actual)
                    elif target < actual and actual > ambient:
                        sensor_values['actual'] = actual - min(0.3, actual - max(ambient, target))
            extruder = _machine_state.temperatures.get('extruder')
            if extruder:
                _machine_state.actual_temp = extruder.get('actual', _machine_state.actual_temp)
                _machine_state.target_temp = extruder.get('target', _machine_state.target_temp)
        time.sleep(0.5)


class stat:
    def __init__(self):
        self._update_attrs()

    def _update_attrs(self):
        with _machine_state.lock:
            self.task_state = _machine_state.task_state
            self.estop = _machine_state.estop
            self.task_mode = _machine_state.task_mode
            self.position = tuple(_machine_state.position)
            self.actual_position = tuple(_machine_state.actual_position)
            self.state = _machine_state.state
            self.file = _machine_state.file
            self.homed = tuple(_machine_state.homed)
            self.interp_state = _machine_state.interp_state
            self.current_line = _machine_state.current_line
            self.total_lines = _machine_state.total_lines
            self.g5x_index = _machine_state.g5x_index
            self.temperatures = {k: dict(v) for k, v in _machine_state.temperatures.items()}
            self.spindle_actual = {k: dict(v) for k, v in _machine_state.spindle_actual.items()}
            self.errors = list(_machine_state.errors)
            self.target_temp = _machine_state.target_temp
            self.actual_temp = _machine_state.actual_temp

    def poll(self):
        self._update_attrs()


class command:
    def __init__(self):
        pass

    def wait_complete(self, timeout=None):
        return RCS_DONE

    def state(self, new_state):
        with _machine_state.lock:
            _machine_state.task_state = new_state
            if new_state == STATE_ESTOP:
                _machine_state.estop = 1
            elif new_state == STATE_ESTOP_RESET:
                _machine_state.estop = 0

    def mode(self, new_mode):
        with _machine_state.lock:
            _machine_state.task_mode = new_mode

    def mdi(self, cmd):
        with _machine_state.lock:
            if _machine_state.task_state != STATE_ON or _machine_state.task_mode != MODE_MDI:
                return
            logger.info(f"Command: Executing MDI -> {cmd}")
            cmd_upper = cmd.upper()

            # WCS Switching
            wcs_map = {"G54": 1, "G55": 2, "G56": 3, "G57": 4, "G58": 5, "G59": 6, "G59.1": 7, "G59.2": 8, "G59.3": 9}
            if cmd_upper in wcs_map:
                _machine_state.g5x_index = wcs_map[cmd_upper]
                return

            # DRO Coordinate Updates
            if cmd_upper.startswith("G0 ") or cmd_upper.startswith("G1 "):
                parts = cmd_upper.split()
                for part in parts:
                    if part.startswith("X"): _machine_state.position[0] = float(part[1:])
                    if part.startswith("Y"): _machine_state.position[1] = float(part[1:])
                    if part.startswith("Z"): _machine_state.position[2] = float(part[1:])
                _machine_state.actual_position = list(_machine_state.position)

            # Spindle Simulation (M3/M4/M5)
            if cmd_upper.startswith("M3") or cmd_upper.startswith("M4"):
                parts = cmd_upper.split()
                speed = next((int(float(p[1:])) for p in parts if p.startswith("S")), 1000)
                for tool_id in _machine_state.spindle_actual:
                    _machine_state.spindle_actual[tool_id]["is_connected"] = True
                    _machine_state.spindle_actual[tool_id]["actual"] = speed
            elif cmd_upper.startswith("M5"):
                for tool_id in _machine_state.spindle_actual:
                    _machine_state.spindle_actual[tool_id]["is_connected"] = False
                    _machine_state.spindle_actual[tool_id]["actual"] = 0

    def abort(self):
        _stop_program_simulation()
        with _machine_state.lock:
            _machine_state.state = 1
            _machine_state.interp_state = INTERP_IDLE
            _machine_state.current_line = 0
            _machine_state.total_lines = 0

    def home(self, axis):
        with _machine_state.lock:
            if 0 <= axis < len(_machine_state.homed):
                _machine_state.homed[axis] = 1

    def jog(self, jog_type, jjogmode, axis, velocity=0, distance=0):
        with _machine_state.lock:
            if jog_type == JOG_INCREMENT and distance != 0:
                if 0 <= axis < len(_machine_state.position):
                    _machine_state.position[axis] += distance
                    _machine_state.actual_position[axis] += distance
            elif jog_type == JOG_CONTINUOUS:
                _machine_state.jogging_axis = axis
                _machine_state.jogging_velocity = velocity
                _machine_state.jog_stop_event.clear()
                if _machine_state.jog_thread is None or not _machine_state.jog_thread.is_alive():
                    _machine_state.jog_thread = threading.Thread(target=_jog_simulation_loop, daemon=True)
                    _machine_state.jog_thread.start()
            elif jog_type == JOG_STOP:
                if _machine_state.jogging_axis == axis:
                    _machine_state.jog_stop_event.set()
                    _machine_state.jogging_axis = None

    def auto(self, auto_cmd, line=0):
        start_thread, stop_thread = False, False
        with _machine_state.lock:
            if auto_cmd == AUTO_RUN:
                _machine_state.interp_state = INTERP_READING
                _machine_state.state = 2
                if line: _machine_state.current_line = line
                if _machine_state.total_lines == 0: _machine_state.total_lines = 1000
                start_thread = True
            elif auto_cmd == AUTO_PAUSE:
                _machine_state.interp_state = INTERP_PAUSED
                _machine_state.state = 1
                stop_thread = True
            elif auto_cmd == AUTO_RESUME:
                _machine_state.interp_state = INTERP_READING
                _machine_state.state = 2
                start_thread = True
            elif auto_cmd == AUTO_STEP:
                _machine_state.current_line += 1
        if stop_thread: _stop_program_simulation()
        if start_thread: _start_program_simulation_if_needed()

    def program_open(self, filepath):
        _stop_program_simulation()
        with _machine_state.lock:
            _machine_state.file = filepath
            _machine_state.current_line = 0
            _machine_state.total_lines = 1000
            _machine_state.interp_state = INTERP_IDLE

    def program_unload(self):
        _stop_program_simulation()
        with _machine_state.lock:
            _machine_state.file = ""
            _machine_state.current_line = 0
            _machine_state.total_lines = 0

    def reset_interpreter(self):
        _stop_program_simulation()
        with _machine_state.lock:
            _machine_state.interp_state = INTERP_IDLE
            _machine_state.current_line = 0
            _machine_state.total_lines = 0

    def set_temperature(self, sensor_name, temp):
        with _machine_state.lock:
            if sensor_name not in _machine_state.temperatures:
                _machine_state.temperatures[sensor_name] = {'actual': 25.0, 'target': float(temp)}
            else:
                _machine_state.temperatures[sensor_name]['target'] = float(temp)
            extruder = _machine_state.temperatures.get('extruder')
            if extruder:
                _machine_state.target_temp = extruder.get('target', _machine_state.target_temp)
                _machine_state.actual_temp = extruder.get('actual', _machine_state.actual_temp)
        if not hasattr(_machine_state,
                       'temp_thread') or _machine_state.temp_thread is None or not _machine_state.temp_thread.is_alive():
            _machine_state.temp_thread = threading.Thread(target=_temp_simulation_loop, daemon=True)
            _machine_state.temp_thread.start()


class error_channel:
    def __init__(self):
        self.errors = []

    def poll(self):
        if self.errors:
            kind, text, time = self.errors.pop(0)
            _machine_state.push_error(kind, text, time)
            return kind, text
        return None