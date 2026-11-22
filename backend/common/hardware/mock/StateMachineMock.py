import collections
import datetime
import logging
import re
import threading
from typing import Any, Deque, Dict, List, Optional, Tuple

from hardware.mock import constants_mock as C
from hardware.mock.MockAxis import MockAxis
from hardware.mock.config import AXIS_LETTERS, MockMachineConfig

logger = logging.getLogger(__name__)

_NINE_ZEROS = (0.0,) * 9
_MDI_WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")


class StateMachineMock:
    """The 'Brain' of the LinuxCNC simulation: what ``linuxcnc.stat()``
    reports. Task / interpreter state, the axes (built from the
    machine's config, see :meth:`configure`), the program being run and
    the error channel. It knows nothing about HAL pins.
    """

    STATE_ESTOP = C.STATE_ESTOP
    STATE_ESTOP_RESET = C.STATE_ESTOP_RESET
    STATE_OFF = C.STATE_OFF
    STATE_ON = C.STATE_ON
    MODE_MANUAL = C.MODE_MANUAL
    MODE_AUTO = C.MODE_AUTO
    MODE_MDI = C.MODE_MDI
    INTERP_IDLE = C.INTERP_IDLE
    INTERP_READING = C.INTERP_READING
    INTERP_PAUSED = C.INTERP_PAUSED
    INTERP_WAITING = C.INTERP_WAITING
    AUTO_RUN = C.AUTO_RUN
    AUTO_PAUSE = C.AUTO_PAUSE
    AUTO_RESUME = C.AUTO_RESUME

    #: Program lines "executed" per second while a program runs.
    LINES_PER_SECOND = 100.0

    def __init__(self, config: Optional[MockMachineConfig] = None):
        self.lock = threading.Lock()

        self.task_state: int = self.STATE_ESTOP
        self.task_mode: int = self.MODE_MANUAL
        self.estop: int = 1
        self.interp_state: int = self.INTERP_IDLE
        self.motion_mode: int = C.TRAJ_MODE_TELEOP
        self.paused: bool = False

        self.file: str = ""
        self.current_line: int = 0
        self.motion_line: int = 0
        self.read_line: int = 0
        self.total_lines: int = 0
        self._line_progress: float = 0.0

        self.g5x_index: int = 1  # G54, as real LinuxCNC reports after boot
        self.feedrate: float = 1.0  # feed override fraction
        self.g5x_offset = _NINE_ZEROS
        self.g92_offset = _NINE_ZEROS
        self.tool_offset = _NINE_ZEROS
        self.spindle: List[Dict[str, Any]] = [{"speed": 0.0, "direction": 0}]

        # MDI modal state (G90 / G91, the last F in units/min)
        self._mdi_relative = False
        self._mdi_feed: Optional[float] = None

        self.errors: List[Dict[str, Any]] = []
        self._max_errors: int = 100
        # ``stat.errors`` (above) is the history the telemetry snapshot
        # reads; ``_pending_errors`` is the error *channel* that
        # ``error_channel.poll()`` drains one tuple at a time — two
        # consumers, as in real NML.
        self._pending_errors: Deque[Tuple[int, str, str]] = collections.deque()

        self.configure(config or MockMachineConfig.default())

    # -----------------------------------------------------------------------
    # Machine shape (from hardware.json)
    # -----------------------------------------------------------------------

    def configure(self, config: MockMachineConfig) -> None:
        """Rebuild the axes and per-joint state for ``config``. Positions
        of axes that exist before and after are kept."""
        with self.lock:
            old = self.__dict__.get("axes", {})  # not getattr: __getattr__ answers 0
            self.config = config
            self.axes: Dict[int, MockAxis] = {
                a.index: MockAxis(
                    a.index,
                    min_limit=a.min_limit,
                    max_limit=a.max_limit,
                    max_velocity=a.max_velocity,
                    position=old[a.index].current_position if a.index in old else max(a.min_limit, min(a.max_limit, 0.0)),
                )
                for a in config.axes
            }
            self.homed: List[int] = [0] * config.joint_count
            self.joints: int = config.joint_count
            self.axis_mask: int = config.axis_mask
            self.max_velocity: float = config.max_velocity
            self.joint = [{"velocity": 0.0, "fault": 0, "homed": 0} for _ in range(config.joint_count)]
            self.axis = [{"velocity": 0.0} for _ in range(9)]
            self._publish_positions()

    def _publish_positions(self) -> None:
        position = [0.0] * 9
        for index, axis in self.axes.items():
            position[index] = axis.current_position
            self.axis[index] = {"velocity": axis.jog_velocity if axis.moving else 0.0}
        self.actual_position = tuple(position)
        self.position = self.actual_position

    def poll(self):
        """``linuxcnc.stat.poll()`` — the mock's state is always live."""

    def __getattr__(self, name):
        """Any other stat field reads as 0 (as an unset NML field would)."""
        if name.startswith("_"):
            raise AttributeError(name)
        logger.debug("stat fallback for '%s' -> 0", name)
        return 0

    # -----------------------------------------------------------------------
    # Task state
    # -----------------------------------------------------------------------

    def trigger_estop(self):
        with self.lock:
            self.estop = 1
            self.task_state = self.STATE_ESTOP
            self.interp_state = self.INTERP_IDLE
            for axis in self.axes.values():
                axis.jog(MockAxis.JOG_STOP, 0.0)
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

    def set_task_mode(self, new_mode: int):
        with self.lock:
            self.task_mode = new_mode
            logger.info("Machine mode changed to: %s", {1: "MANUAL", 2: "AUTO", 3: "MDI"}.get(new_mode, new_mode))

    # -----------------------------------------------------------------------
    # Motion: jog, home, MDI moves
    # -----------------------------------------------------------------------

    def _axis_for(self, index: int, joint_flag: bool) -> Optional[MockAxis]:
        if joint_flag:
            cfg = self.config.axis_of_joint(index)
            return self.axes.get(cfg.index) if cfg else None
        return self.axes.get(index)

    def jog_axis(self, command: int, joint_or_axis: int, velocity: float, distance: float = 0.0, joint_flag: bool = False):
        with self.lock:
            axis = self._axis_for(joint_or_axis, joint_flag)
            if axis:
                axis.jog(command, velocity, distance)

    def home(self, joint: int = -1) -> None:
        """Home ``joint`` (``-1``: all): its axis lands on the configured
        home position (``position_endstop``)."""
        with self.lock:
            joints = range(len(self.homed)) if joint == -1 else [joint]
            for j in joints:
                while len(self.homed) <= j:
                    self.homed.append(0)
                self.homed[j] = 1
                cfg = self.config.axis_of_joint(j)
                if cfg and cfg.index in self.axes:
                    self.axes[cfg.index].set_position(cfg.home)
            self._publish_positions()

    def unhome(self, joint: int = -1) -> None:
        with self.lock:
            if joint == -1:
                self.homed = [0] * len(self.homed)
            elif 0 <= joint < len(self.homed):
                self.homed[joint] = 0

    def execute_mdi(self, cmd: str) -> bool:
        """``G0`` / ``G1`` straight moves (``G90`` / ``G91``, ``F`` in
        units/min) — enough for the UI's MDI line, probing and the
        calibration moves to move the DRO. Other codes are ignored."""
        words = _MDI_WORD.findall(cmd.upper().split(";")[0])
        handled = False
        rapid: Optional[bool] = None
        targets: Dict[int, float] = {}
        with self.lock:
            for letter, value in words:
                number = float(value)
                if letter == "G" and number in (90.0, 91.0):
                    self._mdi_relative = number == 91.0
                    handled = True
                elif letter == "G" and number in (0.0, 1.0):
                    rapid = number == 0.0
                elif letter == "F":
                    self._mdi_feed = number
                elif letter.lower() in AXIS_LETTERS and AXIS_LETTERS.index(letter.lower()) in self.axes:
                    targets[AXIS_LETTERS.index(letter.lower())] = number
            if rapid is None or not targets:
                return handled
            for index, value in targets.items():
                axis = self.axes[index]
                target = axis.current_position + value if self._mdi_relative else value
                cfg = self.config.axis(index)
                fastest = cfg.max_velocity if cfg else self.max_velocity
                speed = fastest if rapid or not self._mdi_feed else min(fastest, self._mdi_feed / 60.0)
                axis.move_to(target, speed)
        return True

    # -----------------------------------------------------------------------
    # Program lifecycle
    # -----------------------------------------------------------------------

    def load_file(self, filepath: str, total_lines: int = 0):
        with self.lock:
            self.file = filepath
            self.total_lines = total_lines
            self._rewind()
            self.interp_state = self.INTERP_IDLE
            logger.info("Loaded file: '%s' with %s lines.", filepath, total_lines)

    def _rewind(self) -> None:
        self.current_line = self.motion_line = self.read_line = 0
        self._line_progress = 0.0

    def run_program(self, start_line: int = 0) -> None:
        with self.lock:
            self._rewind()
            self.current_line = self.motion_line = self.read_line = max(0, int(start_line))
            self._line_progress = float(self.current_line)
            self.interp_state = self.INTERP_READING
            self.paused = False

    def pause_program(self) -> None:
        with self.lock:
            self.interp_state = self.INTERP_PAUSED
            self.paused = True

    def resume_program(self) -> None:
        with self.lock:
            self.interp_state = self.INTERP_READING
            self.paused = False

    def reset_program_state(self):
        """``abort``: the program stops; the loaded file stays loaded."""
        with self.lock:
            self._rewind()
            self.interp_state = self.INTERP_IDLE
            self.paused = False
            for axis in self.axes.values():
                axis.jog(MockAxis.JOG_STOP, 0.0)

    def unload_program(self) -> None:
        with self.lock:
            self.file = ""
            self.total_lines = 0
            self._rewind()
            self.interp_state = self.INTERP_IDLE

    def _advance_program(self, delta_time: float) -> None:
        # A program of unknown length (0 lines) keeps "running" until
        # aborted, as before.
        if self.interp_state != self.INTERP_READING or self.total_lines <= 0:
            return
        self._line_progress = min(float(self.total_lines), self._line_progress + self.LINES_PER_SECOND * self.feedrate * delta_time)
        self.current_line = self.motion_line = self.read_line = int(self._line_progress)
        if self.current_line >= self.total_lines:
            self.interp_state = self.INTERP_IDLE
            logger.info("Program finished: '%s'", self.file)

    # -----------------------------------------------------------------------
    # Error channel
    # -----------------------------------------------------------------------

    def push_error(self, text: str, kind: int = C.OPERATOR_ERROR, time: Optional[str] = None):
        """Add an error to the history (``stat.errors``, re-sent in every
        telemetry snapshot) and to the channel queue that
        ``error_channel.poll()`` drains. The queue is bounded at 4×
        the history so a burst cannot outrun the 10 Hz telemetry loop,
        and a runaway producer cannot leak memory."""
        if time is None:
            time = datetime.datetime.now().isoformat()
        with self.lock:
            self.errors.append({"kind": kind, "text": text, "time": time})
            if len(self.errors) > self._max_errors:
                self.errors.pop(0)
            self._pending_errors.append((kind, text, time))
            while len(self._pending_errors) > self._max_errors * 4:
                dropped = self._pending_errors.popleft()
                logger.warning("Pending error queue overflow; dropping kind=%s text=%r", dropped[0], dropped[1])
            logger.error("Hardware Error [Kind %s]: %s", kind, text)

    def poll_pending_error(self) -> Optional[Tuple[int, str, str]]:
        """One ``(kind, text, time)`` from the channel queue, or ``None``."""
        with self.lock:
            return self._pending_errors.popleft() if self._pending_errors else None

    def clear_errors(self):
        with self.lock:
            self.errors.clear()
            self._pending_errors.clear()
            logger.info("Error history cleared.")

    # -----------------------------------------------------------------------
    # The heartbeat tick
    # -----------------------------------------------------------------------

    def update(self, hal_mock=None, delta_time: float = 0.1):
        """One 100 ms tick: move the axes, advance a running program."""
        with self.lock:
            for axis in self.axes.values():
                axis.update(delta_time)
            self._publish_positions()
            self._advance_program(delta_time)
