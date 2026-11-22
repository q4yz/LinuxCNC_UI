import logging
from pathlib import Path

from hardware.mock import constants_mock

logger = logging.getLogger(__name__)

class CommandMock:
    """Mimics the linuxcnc.command() object."""

    def __init__(self, state_mock, hal_mock):
        self._state_mock = state_mock
        self._hal_mock = hal_mock

    def state(self, new_state):
        """Mimics sending a state command (like turning the machine on)."""
        if new_state == self._state_mock.STATE_ESTOP:
            self._state_mock.trigger_estop()
        elif new_state == self._state_mock.STATE_ESTOP_RESET:
            self._state_mock.reset_estop()
        elif new_state == self._state_mock.STATE_ON:
            # Real LinuxCNC requires the operator to clear E-STOP
            # before turning the machine on. The mock honours the same
            # sequence so a single ``state(STATE_ON)`` is enough to
            # light the dashboard up regardless of the prior boot
            # state — the alternative would force every integration
            # test to POST ``/state`` twice.
            if getattr(self._state_mock, "estop", 0) == 1:
                self._state_mock.reset_estop()
            self._state_mock.turn_on()
        elif new_state == self._state_mock.STATE_OFF:
            self._state_mock.turn_off()

    def abort(self):
        self._state_mock.reset_program_state()

    def auto(self, *args):
        """``command.auto(AUTO_RUN, line)`` / ``AUTO_PAUSE`` / ``AUTO_RESUME``:
        the loaded program runs (its lines advance on the tick), pauses
        or resumes."""
        auto_code = args[0] if args else constants_mock.AUTO_RUN
        if auto_code == constants_mock.AUTO_RUN:
            self._state_mock.run_program(int(args[1]) if len(args) > 1 else 0)
        elif auto_code == constants_mock.AUTO_PAUSE:
            self._state_mock.pause_program()
        elif auto_code == constants_mock.AUTO_RESUME:
            self._state_mock.resume_program()
        return 1

    def home(self, *args):
        """``command.home(joint)`` (``-1``: all). The axis lands on its
        configured home position. E-stop is not enforced, so tests can
        home without clearing it first."""
        self._state_mock.home(int(args[-1]) if args else -1)
        return 1

    def unhome(self, *args):
        """``command.unhome(joint)`` (``-1``: every joint)."""
        self._state_mock.unhome(int(args[-1]) if args else -1)
        return 1

    def teleop_enable(self, *args):
        """Mimics ``linuxcnc.command().teleop_enable``.

        Real LinuxCNC expects ``(value)``; the AxisService calls it
        with ``(1.0, 0)``. The mock is a no-op — the integration
        tests just need the call to succeed.
        """
        return 1

    def jog(self, command: int, joint_flag: bool, joint_or_axis: int, velocity: float = 0.0, distance: float = 0.0):
        """Mimics linuxcnc.command().jog()

        Args:
            command: 0 (STOP), 1 (CONTINUOUS), or 2 (INCREMENT)
            joint_flag: True if jogging a joint, False if jogging an axis letter
            joint_or_axis: The index of the axis/joint (e.g., 0 for X)
            velocity: The jog velocity
            distance: The distance for incremental jogs
        """
        logger.debug(
            "Mock jog called: cmd=%s, joint_flag=%s, axis=%s, vel=%s, dist=%s",
            command, joint_flag, joint_or_axis, velocity, distance
        )

        # Route the command directly to the Trajectory Planner (The Brain)
        self._state_mock.jog_axis(command, joint_or_axis, velocity, distance, joint_flag=bool(joint_flag))

        return 1

    def mode(self, *args):
        """Mimics linuxcnc.command().mode()

        Changes the machine's task mode (MANUAL, AUTO, MDI).
        """
        # Safely extract the integer mode, even if `execute_sync_cmd`
        # accidentally passes a timeout float as the first argument!
        target_mode = 1
        for arg in args:
            if isinstance(arg, int):
                target_mode = arg

        logger.debug(f"Mock mode called with args: {args}. Setting mode to: {target_mode}")

        self._state_mock.set_task_mode(target_mode)

        return 1

    def wait_complete(self, timeout: float = 1.0) -> int:
        """Mimics linuxcnc.command().wait_complete()

        In the real C++ API, this blocks until the NML command is fully
        executed by the motion controller. Since our mock is instantaneous,
        we immediately return 1 (which represents linuxcnc.RCS_DONE).
        """
        return 1

    def setp(self, *args):
        """``command``-channel pin write: ``(pin_name, value)``."""
        self._hal_mock.set_pin(args[0], args[1])
        return 1

    def mdi(self, string: str):
        """Mimics linuxcnc.command().mdi()

        Sends an MDI (Manual Data Input) command string to be executed
        by the interpreter (e.g., 'G0 X0 Y0' or 'M3 S1000').
        """
        logger.debug("Mock mdi called with string: %s", string)


        # Every taker sees the line: the extruder takes its E word,
        # the state machine the axis words.
        self._hal_mock.execute_mdi(string)
        self._state_mock.execute_mdi(string)
        return "success"

    def program_open(self, string: str):
        """``command.program_open(path)``: the length comes from the file,
        so a run advances through its real line count."""
        self._state_mock.load_file(string, _line_count(string))
        return 1

    def feedrate(self, *args):
        """Mimics ``command.feedrate(scale)`` — the stat reports it back as
        ``feedrate`` (1.0 = 100 %), like real LinuxCNC."""
        logger.info("Mock feedrate called with args: %s", args)
        if args:
            with self._state_mock.lock:
                self._state_mock.feedrate = float(args[0])
        return 1

    def maxvel(self, *args):
        """Mimics ``command.maxvel(units_per_s)`` — reported back as
        ``stat.max_velocity``."""
        logger.info("Mock maxvel called with args: %s", args)
        if args:
            with self._state_mock.lock:
                self._state_mock.max_velocity = float(args[0])
        return 1


def _line_count(path: str) -> int:
    try:
        with open(Path(path), "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0
