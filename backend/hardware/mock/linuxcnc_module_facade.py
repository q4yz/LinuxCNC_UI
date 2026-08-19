from hardware.mock.command_mock import CommandMock


class LinuxcncModuleFacade:
    """A drop-in replacement for the real 'linuxcnc' Python module."""

    def __init__(self, state_mock, hal_mock):
        self._state = state_mock
        self._hal_mock = hal_mock

        # Expose the NML constants directly on the module so things like
        # `if stat.task_state == linuxcnc.STATE_ESTOP:` work natively!
        self.STATE_ESTOP = state_mock.STATE_ESTOP
        self.STATE_ESTOP_RESET = state_mock.STATE_ESTOP_RESET
        self.STATE_OFF = state_mock.STATE_OFF
        self.STATE_ON = state_mock.STATE_ON

        self.INTERP_IDLE = state_mock.INTERP_IDLE
        self.INTERP_READING = state_mock.INTERP_READING
        self.INTERP_PAUSED = state_mock.INTERP_PAUSED
        self.INTERP_WAITING = state_mock.INTERP_WAITING

    def stat(self):
        """Mimics linuxcnc.stat().
        Because our StateMachineMock already has .poll(), .estop, .task_state, etc.,
        we can just return it directly!
        """
        return self._state

    def command(self):
        """Mimics linuxcnc.command()."""
        return CommandMock(self._state, self._hal_mock)

    def error_channel(self):
        """Mimics linuxcnc.error_channel()."""
        error_ch = self._state
        class _ErrorChannel:
            def poll(self):
                return None  # no pending error this tick

            @property
            def errors(self):
                return list(getattr(error_ch, "errors", []) or [])

        return _ErrorChannel()