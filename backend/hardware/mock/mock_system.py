import json
import time
import threading
import logging
from typing import Any, Optional, List

from hardware.mock.mock_component import MockComponent
from hardware.mock.mock_heater import MockHeater
from hardware.mock.mock_spindle_digital import MockSpindleDigital

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("linuxcnc_mock")

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



class MockSystemOrchestrator:
    def __init__(self):
        self.components: List[MockComponent] = []
        self.lock = threading.Lock()
        self._start_simulation_loop()

    def clear(self):
        with self.lock:
            self.components.clear()

    def add_component(self, component: MockComponent):
        with self.lock:
            self.components.append(component)

    def read_pin(self, pin_name: str) -> Optional[Any]:
        with self.lock:
            for comp in self.components:
                val = comp.read_pin(pin_name)
                if val is not None: return val
        return None

    def set_pin(self, pin_name: str, value: Any) -> bool:
        with self.lock:
            for comp in self.components:
                if comp.set_pin(pin_name, value): return True
        return False

    def execute_gcode(self, gcode: str):
        with self.lock:
            for comp in self.components:
                comp.execute_gcode(gcode)

    def _start_simulation_loop(self):
        def loop():
            last_time = time.time()
            while True:
                now = time.time()
                dt = now - last_time
                last_time = now
                with self.lock:
                    for comp in self.components:
                        comp.update(dt)
                time.sleep(0.1)  # 10 ticks/sec

        threading.Thread(target=loop, daemon=True, name="mock_system_loop").start()


mock_system = MockSystemOrchestrator()


def reseed_from_hardware_json():
    """Reads hardware.json and dynamically spawns components."""
    mock_system.clear()

    payload = None
    for path in _default_hardware_paths():
        if path.exists():
            try:
                with path.open(encoding="utf-8") as fp:
                    payload = json.load(fp)
                    break
            except Exception:
                pass

    if not isinstance(payload, dict) or not isinstance(payload.get("tools"), list):
        return

    for tool in payload["tools"]:
        t_type = tool.get("type")
        t_id = tool.get("id") or tool.get("sensor")
        if not t_id:
            continue

        if t_type in ("heater", "heated_bed", "extruder"):
            mock_system.add_component(MockHeater(t_id))
        elif t_type == "spindle_digital":
            mock_system.add_component(MockSpindleDigital(t_id))


# ===========================================================================
# 2. CORE LINUXCNC STATE (Legacy Compatibility)
# ===========================================================================

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

        # Jog/Program state
        self.program_thread = None
        self.program_stop_event = threading.Event()
        self.jogging_axis = None
        self.jogging_velocity = 0.0
        self.jog_thread = None
        self.jog_stop_event = threading.Event()

        self.errors = []
        self._max_errors = 100

    def push_error(self, kind: int, text: str, time: str) -> None:
        with self.lock:
            self.errors.append({"kind": kind, "text": text, "time": time})
            if len(self.errors) > self._max_errors:
                del self.errors[: len(self.errors) - self._max_errors]


_machine_state = SharedMachineState()


# Jog & Program Simulation Threads
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


def _start_program_simulation_if_needed():
    with _machine_state.lock:
        if _machine_state.program_thread and _machine_state.program_thread.is_alive(): return
        _machine_state.program_stop_event.clear()
        _machine_state.program_thread = threading.Thread(target=_program_simulation_loop, daemon=True)
        _machine_state.program_thread.start()


def _stop_program_simulation():
    with _machine_state.lock:
        thread = _machine_state.program_thread
        _machine_state.program_stop_event.set()
        _machine_state.program_thread = None
    if thread and thread.is_alive():
        thread.join(timeout=0.5)


def is_program_loaded() -> bool:
    with _machine_state.lock: return bool(_machine_state.file)


# ===========================================================================
# 3. NML FACADE CLASSES (stat, command, error_channel)
# ===========================================================================

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
            self.errors = list(_machine_state.errors)

        # Bridge legacy dicts by asking the new mock_system!
        self.temperatures = {}
        self.spindle_actual = {}
        with mock_system.lock:
            for comp in mock_system.components:
                if isinstance(comp, MockHeater):
                    self.temperatures[comp.tool_id] = comp.get_legacy_state()
                elif isinstance(comp, MockSpindleDigital):
                    self.spindle_actual[comp.tool_id] = comp.get_legacy_state()

        # Legacy single-extruder fallbacks
        legacy_extruder = self.temperatures.get('extruder')
        self.actual_temp = legacy_extruder["actual"] if legacy_extruder else 25.0
        self.target_temp = legacy_extruder["target"] if legacy_extruder else 0.0

    def poll(self):
        self._update_attrs()


class command:
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
        with _machine_state.lock: _machine_state.task_mode = new_mode

    def mdi(self, cmd):
        with _machine_state.lock:
            if _machine_state.task_state != STATE_ON or _machine_state.task_mode != MODE_MDI: return

            cmd_upper = cmd.upper()

            # WCS
            wcs_map = {"G54": 1, "G55": 2, "G56": 3, "G57": 4, "G58": 5, "G59": 6, "G59.1": 7, "G59.2": 8, "G59.3": 9}
            if cmd_upper in wcs_map:
                _machine_state.g5x_index = wcs_map[cmd_upper]
                return

            # DRO Updates
            if cmd_upper.startswith("G0 ") or cmd_upper.startswith("G1 "):
                parts = cmd_upper.split()
                for part in parts:
                    if part.startswith("X"): _machine_state.position[0] = float(part[1:])
                    if part.startswith("Y"): _machine_state.position[1] = float(part[1:])
                    if part.startswith("Z"): _machine_state.position[2] = float(part[1:])
                _machine_state.actual_position = list(_machine_state.position)

        # Send GCODE to components (Spindles, etc)
        mock_system.execute_gcode(cmd)

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

    def set_temperature(self, sensor_name, temp):
        # Bridge legacy NML command into the Component System
        pin_target = f"{sensor_name}.temp.target"
        success = mock_system.set_pin(pin_target, temp)
        if not success:
            logger.warning(f"Mock: No heater found for {sensor_name}")


class error_channel:
    def __init__(self):
        self.errors = []

    def poll(self):
        if self.errors:
            kind, text, time = self.errors.pop(0)
            _machine_state.push_error(kind, text, time)
            return kind, text
        return None


# ===========================================================================
# 4. MOCK HAL MODULE
# ===========================================================================
class hal_mock:
    """Provides a fake `hal` module interface so the backend can read pins."""

    @staticmethod
    def get_value(pin_name: str) -> Any:
        return mock_system.read_pin(pin_name)

    @staticmethod
    def set_p(pin_name: str, value: Any) -> None:
        mock_system.set_pin(pin_name, value)


hal = hal_mock()