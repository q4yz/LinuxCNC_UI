from hardware.mock import constants_mock
from hardware.mock.facade.CommandMock import CommandMock


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

        # NML jog/trajectory-mode constants. The production
        # ``hardware.connection`` module imports these via
        # ``getattr(linuxcnc, "JOG_CONTINUOUS", 1)`` and the mock had
        # no equivalent until now — expose every constant the
        # ``constants_mock`` module ships so a single ``from hardware
        # import linuxcnc`` resolves every constant the tests use.
        for _name in (
            "JOG_STOP",
            "JOG_INCREMENT",
            "JOG_CONTINUOUS",
            "TRAJ_MODE_FREE",
            "TRAJ_MODE_TELEOP",
            "MODE_MANUAL",
            "MODE_MDI",
            "MODE_AUTO",
            "AUTO_RUN",
            "AUTO_PAUSE",
            "AUTO_RESUME",
            "AUTO_STEP",
        ):
            setattr(self, _name, getattr(constants_mock, _name))

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
        """Mimics ``linuxcnc.error_channel()``.

        ``poll()`` drains one pending error tuple from the mock
        state machine's queue and returns ``(kind, text)`` — exactly
        the shape ``python-linuxcnc`` ships to callers. The
        ``StateMachineMock`` keeps a separate FIFO queue
        (``_pending_errors``) distinct from its bounded
        ``errors`` history, mirroring the real NML topology where
        ``stat.errors`` (history) and the error channel queue
        (real-time events) are independent consumers.

        ``errors`` exposes the bounded history as a defensive copy so
        tests that introspect the queue cannot accidentally mutate
        the underlying buffer.
        """
        error_ch = self._state

        class _ErrorChannel:
            def poll(self):
                pending = error_ch.poll_pending_error()
                if pending is None:
                    return None
                # ``poll_pending_error`` returns ``(kind, text, time)``
                # so the channel sidecar can carry a timestamp
                # without forcing the NML-shaped ``(kind, text)``
                # contract to widen.
                kind, text, _time = pending
                return (kind, text)

            @property
            def errors(self):
                return list(getattr(error_ch, "errors", []) or [])

        return _ErrorChannel()