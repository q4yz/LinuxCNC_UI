import datetime
import logging
import threading
from typing import List

from hardware.mock.axis_mock import MockAxis

logger = logging.getLogger(__name__)

class StateMachineMock:
    """The 'Brain' of the LinuxCNC simulation.

    Handles high-level machine states, interpreter status, and program
    lifecycle. It does not know about physical pins, only system-wide
    modes and statuses.
    """

    # Simulated LinuxCNC NML Constants
    STATE_ESTOP = 1
    STATE_ESTOP_RESET = 2
    STATE_OFF = 3
    STATE_ON = 4

    INTERP_IDLE = 1
    INTERP_READING = 2
    INTERP_PAUSED = 3
    INTERP_WAITING = 4

    def __init__(self):
        self.lock = threading.Lock()

        # NML variables read by StateService and ProgramService
        self.task_state: int = self.STATE_ESTOP
        self.task_mode: int = self.MODE_MANUAL
        self.estop: int = 1
        self.interp_state: int = self.INTERP_IDLE
        self.file: str = ""
        self.current_line: int = 0
        self.total_lines: int = 0
        self.homed: List[int] = [0, 0, 0]  # X, Y, Z flags
        self.motion_mode: int = 3  # Default to TRAJ_MODE_TELEOP

        # Explicitly initialize positions so they can be safely mutated
        self.actual_position = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.position = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        # The State Machine owns the physical axes (Trajectory Planner simulation)
        self.axes = {
            0: MockAxis(0),  # X
            1: MockAxis(1),  # Y
            2: MockAxis(2)   # Z
        }

        # Diagnostics
        self.errors: List[dict] = []
        self._max_errors: int = 100

        logger.debug("StateMachineMock initialized.")

    def poll(self):
        """Mock for linuxcnc.stat.poll().

        The real LinuxCNC requires this to fetch the latest NML buffer.
        In our mock, the state is always live, so this is a no-op to
        satisfy the caller's signature.
        """
        pass

    # -----------------------------------------------------------------------
    # State Transitions (Triggered by HTTP Routers / Services)
    # -----------------------------------------------------------------------

    def trigger_estop(self):
        with self.lock:
            self.estop = 1
            self.task_state = self.STATE_ESTOP
            self.interp_state = self.INTERP_IDLE
            logger.warning("E-STOP triggered.")

    def reset_estop(self):
        with self.lock:
            self.estop = 0
            self.task_state = self.STATE_ESTOP_RESET
            logger.info("E-STOP reset.")

    def turn_on(self):
        with self.lock:
            if self.estop == 1:
                logger.error("Attempted to turn on machine while in E-STOP.")
                raise RuntimeError("Cannot turn on machine while in E-STOP.")
            self.task_state = self.STATE_ON
            logger.info("Machine turned ON.")

    def turn_off(self):
        with self.lock:
            self.task_state = self.STATE_OFF
            logger.info("Machine turned OFF.")

    def __getattr__(self, name):
        """
        Magic method: If the UI asks for a property we haven't explicitly
        defined, it falls through to this method.
        """

        defaults = {
            "task_mode": 1,  # linuxcnc.MODE_MANUAL
            "task_state": 4,  # linuxcnc.STATE_ON
            "estop": 0,  # Not in E-Stop
            "interp_state": 1,  # linuxcnc.INTERP_IDLE
            "g5x_offset": (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            "g92_offset": (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            "tool_offset": (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            "spindle": [{"speed": 0.0, "direction": 0}],
            "axis": [{"velocity": 0.0, "fault": 0}] * 3,
            "joint": [{"velocity": 0.0, "fault": 0}] * 3,
            "homed": (1, 1, 1),
            "file": "",
            "motion_line": 0,
            "current_line": 0,
            "read_line": 0,
            "paused": False,
        }

        # If it's not in our defaults, just return 0 to be safe
        val = defaults.get(name, 0)
        logger.debug(f"__getattr__ fallback accessed for property: '{name}', returning: {val}")
        return val

    # -----------------------------------------------------------------------
    # Motion & Jogging
    # -----------------------------------------------------------------------

    def jog_axis(self, command: int, joint_or_axis: int, velocity: float, distance: float = 0.0):
        """Routes a jog command to the specific axis."""
        with self.lock:
            axis = self.axes.get(joint_or_axis)
            if axis:
                axis.jog(command, velocity, distance)

    def set_task_mode(self, new_mode: int):
        with self.lock:
            self.task_mode = new_mode
            mode_names = {1: "MANUAL", 2: "AUTO", 3: "MDI"}
            logger.info(f"Machine mode changed to: {mode_names.get(new_mode, new_mode)}")
    # -----------------------------------------------------------------------
    # Program Lifecycle
    # -----------------------------------------------------------------------

    def load_file(self, filepath: str, total_lines: int = 0):
        with self.lock:
            self.file = filepath
            self.current_line = 0
            self.total_lines = total_lines
            self.interp_state = self.INTERP_IDLE
            logger.info(f"Loaded file: '{filepath}' with {total_lines} lines.")

    def reset_program_state(self):
        with self.lock:
            self.file = ""
            self.current_line = 0
            self.total_lines = 0
            self.interp_state = self.INTERP_IDLE
            logger.debug("Program state reset.")

    # -----------------------------------------------------------------------
    # Error Management
    # -----------------------------------------------------------------------

    def push_error(self, text: str, kind: int = 11, time: str = None):
        """Builds an error dictionary and pushes it into the bounded history."""
        # Auto-generate a timestamp if one isn't provided (great for live use)
        if time is None:
            time = datetime.datetime.now().isoformat()

        error_dict = {
            "kind": kind,
            "text": text,
            "time": time
        }

        with self.lock:
            self.errors.append(error_dict)
            if len(self.errors) > self._max_errors:
                self.errors.pop(0)
            logger.error(f"Hardware Error [Kind {kind}]: {text}")

    def clear_errors(self):
        with self.lock:
            self.errors.clear()
            logger.info("Error history cleared.")

    # -----------------------------------------------------------------------
    # The Heartbeat Tick
    # -----------------------------------------------------------------------

    def update(self, hal_mock, delta_time: float = 0.1):
        """Evaluates system-wide rules based on the HAL's physical state.

        Called every 100ms by the main LinuxCNCMock background thread.
        This is where the Brain checks the Muscle.
        """
        with self.lock:
            # 1. Tick all axes forward in time
            for axis in self.axes.values():
                axis.update(delta_time)

            # 2. Sync the mathematical positions to the NML buffer (UI reads this)
            self.actual_position = (
                self.axes[0].current_position,
                self.axes[1].current_position,
                self.axes[2].current_position,
                0.0, 0.0, 0.0, 0.0, 0.0, 0.0
            )
            self.position = self.actual_position

            # 3. Write back to HAL so virtual pins reflect the physical state
            # hal_mock.set_p("joint.0.motor-pos-fb", self.axes[0].current_position)
            # hal_mock.set_p("joint.1.motor-pos-fb", self.axes[1].current_position)
            # hal_mock.set_p("joint.2.motor-pos-fb", self.axes[2].current_position)
            #
            # # 4. Check limit switches
            # # Using get_p ensures compatibility with the new HalModuleFacade
            # if hal_mock.get_p("limit-switch-x-max") is True:
            #     if self.estop == 0:
            #         logger.warning("HAL trigger: limit-switch-x-max activated. Forcing E-STOP.")
            #         self.push_error("Joint 0 on limit switch error")
            #         self.trigger_estop()
            #
            # # 5. Simulate program progression if running
            # if self.interp_state in (self.INTERP_READING, self.INTERP_WAITING):
            #     if self.current_line < self.total_lines:
            #         self.current_line += 1
            #         # Avoid spamming the log on every single line increment
            #         if self.current_line % 100 == 0:
            #             logger.debug(f"Program progression: line {self.current_line}/{self.total_lines}")
            #     else:
            #         self.interp_state = self.INTERP_IDLE
            #         logger.info(f"Program finished execution: '{self.file}'")