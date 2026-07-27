import time
import threading
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("linuxcnc_mock")

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
class SharedMachineState:
    def __init__(self):
        self.task_state = STATE_ESTOP
        self.estop = 1
        self.task_mode = MODE_MANUAL
        self.position = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.actual_position = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.state = 1  # 1 = Idle, 2 = Running
        self.file = ""
        self.homed = [0, 0, 0]
        self.interp_state = INTERP_IDLE
        self.current_line = 0
        self.total_lines = 0
        self.g5x_index = 1  # 1 = G54 (default)
        
        # Temperature Simulation State (multi-sensor dictionary)
        # Example sensors: extruder, bed, cpu
        self.temperatures = {
            'extruder': {'actual': 25.0, 'target': 0.0},
            'bed': {'actual': 25.0, 'target': 0.0},
            'cpu': {'actual': 40.0}  # CPU has no controllable target
        }
        # Backwards-compatible single-sensor fields (kept for older callers)
        self.target_temp = self.temperatures.get('extruder', {}).get('target', 0.0)
        self.actual_temp = self.temperatures.get('extruder', {}).get('actual', 25.0)
        
        self.lock = threading.Lock()

        # Program execution simulation state
        self.program_thread = None
        self.program_stop_event = threading.Event()
        
        # Jog simulation state
        self.jogging_axis = None
        self.jogging_velocity = 0.0
        self.jog_thread = None
        self.jog_stop_event = threading.Event()

_machine_state = SharedMachineState()

def _jog_simulation_loop():
    """Background thread to actually move coordinates during a continuous jog in the mock"""
    while not _machine_state.jog_stop_event.is_set():
        with _machine_state.lock:
            if _machine_state.jogging_axis is not None:
                # Velocity is units/min. Update 10 times a sec (0.1s tick)
                delta = (_machine_state.jogging_velocity / 60.0) * 0.1
                _machine_state.position[_machine_state.jogging_axis] += delta
                _machine_state.actual_position[_machine_state.jogging_axis] += delta

        time.sleep(0.1)


def _program_simulation_loop():
    """Background thread that advances ``current_line`` while a G-code program runs.

    The loop is shared by ``AUTO_RUN`` and ``AUTO_RESUME``; the
    ``program_stop_event`` short-circuits it on ``AUTO_PAUSE`` and
    ``abort`` so callers can pause / resume without recreating the
    thread.  When the program reaches its end the interpreter is
    flipped back to ``INTERP_IDLE`` so the WebSocket telemetry loop
    reflects the new state on the next 100 ms tick.
    """
    while not _machine_state.program_stop_event.is_set():
        advance = False
        with _machine_state.lock:
            if (
                _machine_state.interp_state == INTERP_READING
                and _machine_state.current_line < _machine_state.total_lines
            ):
                _machine_state.current_line += 1
                if _machine_state.current_line >= _machine_state.total_lines:
                    _machine_state.interp_state = INTERP_IDLE
                advance = True
            elif (
                _machine_state.interp_state == INTERP_READING
                and _machine_state.current_line >= _machine_state.total_lines
            ):
                _machine_state.interp_state = INTERP_IDLE
        if not advance:
            # Either we paused, the program finished, or the lock was
            # contended; wait briefly before re-evaluating.
            time.sleep(0.1)
            continue
        time.sleep(0.1)


def _start_program_simulation_if_needed() -> None:
    """Spawn the program simulation thread if it is not already running."""
    with _machine_state.lock:
        thread = _machine_state.program_thread
        if thread is not None and thread.is_alive():
            return
        _machine_state.program_stop_event.clear()
        _machine_state.program_thread = threading.Thread(
            target=_program_simulation_loop,
            daemon=True,
            name="linuxcnc_mock-program-simulation",
        )
        _machine_state.program_thread.start()
    logger.info("Mock: program simulation thread started")


def _stop_program_simulation() -> None:
    """Signal the program simulation thread to exit and clear the handle."""
    with _machine_state.lock:
        thread = _machine_state.program_thread
        _machine_state.program_stop_event.set()
        _machine_state.program_thread = None
    if thread is not None and thread.is_alive():
        thread.join(timeout=0.5)
    logger.info("Mock: program simulation thread stopped")


def _temp_simulation_loop():
    """Background thread to simulate heater physics for all temperature sensors."""
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

# --- Mock Stat Class ---
class stat:
    def __init__(self):
        self._update_attrs()

    def _update_attrs(self):
        """Syncs instance attributes with the shared state."""
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
            # Expose multi-sensor temperatures as a dict for callers
            # (shallow copy to avoid exposing internal lock-managed dict directly)
            self.temperatures = {k: dict(v) for k, v in _machine_state.temperatures.items()}
            # Backwards-compatible single-sensor fields
            self.target_temp = _machine_state.target_temp
            self.actual_temp = _machine_state.actual_temp

    def poll(self):
        """Simulates polling the machine state."""
        self._update_attrs()

# --- Mock Command Class ---
class command:
    def __init__(self):
        pass

    def wait_complete(self, timeout=None):
        """Mocks the block for command completion."""
        return RCS_DONE

    def state(self, new_state):
        with _machine_state.lock:
            _machine_state.task_state = new_state
            if new_state == STATE_ESTOP:
                _machine_state.estop = 1
                logger.info("Command: ESTOP Triggered")
            elif new_state == STATE_ESTOP_RESET:
                _machine_state.estop = 0
                logger.info("Command: ESTOP Reset")
            elif new_state == STATE_ON:
                logger.info("Command: Machine ON")
            elif new_state == STATE_OFF:
                logger.info("Command: Machine OFF")

    def mode(self, new_mode):
        with _machine_state.lock:
            _machine_state.task_mode = new_mode
            mode_str = {1: "MANUAL", 2: "AUTO", 3: "MDI"}.get(new_mode, "UNKNOWN")
            logger.info(f"Command: Mode set to {mode_str}")

    def mdi(self, cmd):
        with _machine_state.lock:
            if _machine_state.task_state != STATE_ON:
                logger.warning(f"Ignored MDI (Machine not ON): {cmd}")
                return
            if _machine_state.task_mode != MODE_MDI:
                logger.warning(f"Ignored MDI (Not in MDI mode): {cmd}")
                return
            
            logger.info(f"Command: Executing MDI -> {cmd}")
            
            # Mock WCS switching (G54 - G59.3)
            cmd_upper = cmd.upper()
            wcs_map = {
                "G54": 1, "G55": 2, "G56": 3, "G57": 4, "G58": 5,
                "G59": 6, "G59.1": 7, "G59.2": 8, "G59.3": 9
            }
            if cmd_upper in wcs_map:
                _machine_state.g5x_index = wcs_map[cmd_upper]
                logger.info(f"Mock: Switched WCS to {cmd_upper} (Index: {_machine_state.g5x_index})")
                return

            # Extremely basic G0/G1 mock parsing for DRO updates
            if cmd_upper.startswith("G0 ") or cmd_upper.startswith("G1 "):
                parts = cmd_upper.split()
                for part in parts:
                    if part.startswith("X"): _machine_state.position[0] = float(part[1:])
                    if part.startswith("Y"): _machine_state.position[1] = float(part[1:])
                    if part.startswith("Z"): _machine_state.position[2] = float(part[1:])
                _machine_state.actual_position = list(_machine_state.position)

    def abort(self):
        # Stop the simulation thread *before* mutating shared state
        # so the worker exits while holding the lock-free tail of
        # its loop and cannot race the ``current_line`` reset.
        _stop_program_simulation()
        with _machine_state.lock:
            _machine_state.state = 1
            _machine_state.interp_state = INTERP_IDLE
            _machine_state.current_line = 0
            _machine_state.total_lines = 0
            logger.info("Command: Abort / Stop")

    def home(self, axis):
        with _machine_state.lock:
            if axis >= 0 and axis < len(_machine_state.homed):
                _machine_state.homed[axis] = 1
            logger.info(f"Command: Home Axis {axis}")

    def jog(self, jog_type, jjogmode, axis, velocity=0, distance=0):
        with _machine_state.lock:
            # Mock incremental jog to actually move the DRO
            if jog_type == JOG_INCREMENT and distance != 0:
                if axis >= 0 and axis < len(_machine_state.position):
                    _machine_state.position[axis] += distance
                    _machine_state.actual_position[axis] += distance
            elif jog_type == JOG_CONTINUOUS:
                _machine_state.jogging_axis = axis
                _machine_state.jogging_velocity = velocity
                _machine_state.jog_stop_event.clear()
                if _machine_state.jog_thread is None or not _machine_state.jog_thread.is_alive():
                    _machine_state.jog_thread = threading.Thread(target=_jog_simulation_loop, daemon=True)
                    _machine_state.jog_thread.start()
                logger.info(f"Mock: JOG_CONTINUOUS started on Axis {axis} at Vel {velocity}")
            elif jog_type == JOG_STOP:
                if _machine_state.jogging_axis == axis:
                    _machine_state.jog_stop_event.set()
                    _machine_state.jogging_axis = None
                logger.info(f"Mock: JOG_STOP received for Axis {axis}")
        logger.info(f"Command: Jog Axis {axis} (Type: {jog_type}, Vel: {velocity}, Dist: {distance})")

    def auto(self, auto_cmd, line=0):
        # Run, pause, and resume all need to start or signal the
        # simulation thread outside the lock so we capture the
        # current view of state up front and then apply the
        # transition.  ``_stop_program_simulation`` acquires the
        # same non-reentrant ``_machine_state.lock`` internally, so
        # it must never be called from inside a ``with lock:`` block
        # (otherwise the handler deadlocks against itself).
        start_thread = False
        stop_thread = False
        with _machine_state.lock:
            if auto_cmd == AUTO_RUN:
                _machine_state.interp_state = INTERP_READING
                _machine_state.state = 2  # 2 = Running
                if line:
                    _machine_state.current_line = line
                if _machine_state.total_lines == 0:
                    _machine_state.total_lines = 1000
                start_thread = True
                logger.info(
                    f"Command: Auto Run from line {_machine_state.current_line} "
                    f"(total={_machine_state.total_lines})"
                )
            elif auto_cmd == AUTO_PAUSE:
                _machine_state.interp_state = INTERP_PAUSED
                _machine_state.state = 1
                stop_thread = True
                logger.info("Command: Auto Pause")
            elif auto_cmd == AUTO_RESUME:
                _machine_state.interp_state = INTERP_READING
                _machine_state.state = 2
                start_thread = True
                logger.info("Command: Auto Resume")
            elif auto_cmd == AUTO_STEP:
                _machine_state.current_line += 1
                logger.info("Command: Auto Step")
        if stop_thread:
            _stop_program_simulation()
        if start_thread:
            _start_program_simulation_if_needed()

    def program_open(self, filepath):
        # ``program_open`` may be called when a run is already in
        # progress; abort the simulation thread first so the new
        # file's line count is the authoritative one.
        _stop_program_simulation()
        with _machine_state.lock:
            _machine_state.file = filepath
            _machine_state.current_line = 0
            _machine_state.total_lines = 1000
            _machine_state.interp_state = INTERP_IDLE
            logger.info(
                f"Command: Program Open -> {filepath} "
                f"(total_lines={_machine_state.total_lines})"
            )

    def reset_interpreter(self):
        _stop_program_simulation()
        with _machine_state.lock:
            _machine_state.interp_state = INTERP_IDLE
            _machine_state.current_line = 0
            _machine_state.total_lines = 0
            logger.info("Command: Reset Interpreter")

    def set_temperature(self, sensor_name, temp):
        with _machine_state.lock:
            # Create sensor entry if missing
            if sensor_name not in _machine_state.temperatures:
                _machine_state.temperatures[sensor_name] = {'actual': 25.0, 'target': float(temp)}
            else:
                _machine_state.temperatures[sensor_name]['target'] = float(temp)

            # Keep single-sensor compatibility fields in sync with 'extruder'
            extruder = _machine_state.temperatures.get('extruder')
            if extruder:
                _machine_state.target_temp = extruder.get('target', _machine_state.target_temp)
                _machine_state.actual_temp = extruder.get('actual', _machine_state.actual_temp)

        # Ensure the dedicated temperature simulation loop is running
        if not hasattr(_machine_state, 'temp_thread') or _machine_state.temp_thread is None or not _machine_state.temp_thread.is_alive():
            _machine_state.temp_thread = threading.Thread(target=_temp_simulation_loop, daemon=True)
            _machine_state.temp_thread.start()

        logger.info(f"Command: Set Temperature Target for {sensor_name} to {temp}°C")

# --- Mock Error Channel ---
class error_channel:
    def __init__(self):
        self.errors = []

    def poll(self):
        if self.errors:
            return self.errors.pop(0)
        return None
