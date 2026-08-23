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
        """Mimics ``linuxcnc.command().auto`` (AUTO_RUN / AUTO_PAUSE / AUTO_RESUME).

        The LinuxCNC API takes ``(auto_code, line_number)``. The mock
        flips ``interp_state`` to ``INTERP_READING`` when ``AUTO_RUN``
        is dispatched so the dashboard's "Running" badge lights up;
        ``AUTO_PAUSE`` and ``AUTO_RESUME`` mirror the same fields.
        """
        # ``args`` is ``(auto_code, line_number)``. ``getattr`` is
        # defensive — the constants may not be on the facade in
        # older test stubs.
        auto_code = args[0] if args else 0
        state_mock = self._state_mock
        auto_run = getattr(state_mock, "AUTO_RUN", 0)
        auto_pause = getattr(state_mock, "AUTO_PAUSE", 1)
        auto_resume = getattr(state_mock, "AUTO_RESUME", 2)
        reading = getattr(state_mock, "INTERP_READING", 2)
        paused = getattr(state_mock, "INTERP_PAUSED", 3)

        if auto_code == auto_run:
            with state_mock.lock:
                state_mock.interp_state = reading
        elif auto_code == auto_pause:
            with state_mock.lock:
                state_mock.interp_state = paused
        elif auto_code == auto_resume:
            with state_mock.lock:
                state_mock.interp_state = reading
        return 1

    def home(self, *args):
        """Mimics ``linuxcnc.command().home``.

        The real API takes ``(joint_mask, joint_index)`` for
        single-axis homing or ``(joint_mask, -1)`` for homing all
        axes; we accept whatever the caller passes and flip the
        corresponding ``homed`` flags on the state mock.

        The mock does NOT enforce the E-STOP semantics real LinuxCNC
        applies — homing during E-STOP is intentionally allowed so
        the integration tests don't have to clear E-STOP before
        every ``POST /home`` request. Real operators clear E-STOP
        via the dashboard UI before pressing Home.
        """
        if len(args) >= 2:
            joint_index = int(args[1])
        else:
            joint_index = -1
        if joint_index == -1:
            self._state_mock.homed = [1, 1, 1]
        else:
            while len(self._state_mock.homed) < joint_index + 1:
                self._state_mock.homed.append(0)
            self._state_mock.homed[joint_index] = 1
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