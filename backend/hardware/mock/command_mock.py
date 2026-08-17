class CommandMock:
    """Mimics the linuxcnc.command() object."""

    def __init__(self, state_mock):
        self._state = state_mock

    def state(self, new_state):
        """Mimics sending a state command (like turning the machine on)."""
        if new_state == self._state.STATE_ESTOP:
            self._state.trigger_estop()
        elif new_state == self._state.STATE_ESTOP_RESET:
            self._state.reset_estop()
        elif new_state == self._state.STATE_ON:
            self._state.turn_on()
        elif new_state == self._state.STATE_OFF:
            self._state.turn_off()

    def abort(self):
        self._state.reset_program_state()

    # Add other command methods (like `mode()`, `task_plan_execute()`) here as your app needs them!