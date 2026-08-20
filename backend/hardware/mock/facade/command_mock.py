import logging

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
            self._state_mock.turn_on()
        elif new_state == self._state_mock.STATE_OFF:
            self._state_mock.turn_off()

    def abort(self):
        self._state_mock.reset_program_state()

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
        self._state_mock.jog_axis(command, joint_or_axis, velocity, distance)

        return 1

    def mode(self, *args):
        """Mimics linuxcnc.command().mode()

        Changes the machine's task mode (MANUAL, AUTO, MDI).
        """
        import logging
        logger = logging.getLogger(__name__)

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
        """Mimics setting a hardware/HAL pin value via the command channel.

        Typically receives: (pin_name, value)
        """


        logger.info(f"Mock setp called with args: {args}")

        self._hal_mock.set_pin(args[0], args[1])

        # In the future, if you want your mock UI to actually react to this
        # (like updating a simulated heater target temperature), you could
        # route this to your HAL mock here!
        # Example: self._state.hal_mock.set_p(args[0], args[1])

        return 1

    def mdi(self, string: str):
        """Mimics linuxcnc.command().mdi()

        Sends an MDI (Manual Data Input) command string to be executed
        by the interpreter (e.g., 'G0 X0 Y0' or 'M3 S1000').
        """
        logger.debug("Mock mdi called with string: %s", string)


        success = self._hal_mock.execute_mdi(string) or self._state_mock.execute_mdi(string)

        if not success:
            pass
            #raise ValueError("Mock mdi failed")

        return "success"

    def program_open(self, string: str):
        """Mimics linuxcnc.command().program_open()"""
        self._state_mock.load_file(string)
        return 1

    # Add other command methods (like `mode()`, `task_plan_execute()`) here as your app needs them!

    # Add other command methods (like `mode()`, `task_plan_execute()`) here as your app needs them!