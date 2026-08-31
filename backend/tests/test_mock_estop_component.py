"""Tests for the always-on ``MockEStopComponent``.

These tests are mock-only — they exercise the
``StateMachineMock`` + ``HalMock`` + ``MockEStopComponent``
integration that the real ``webgui.estop`` HAL file would
otherwise exercise on a LinuxCNC host. They run on every CI
because the mock layer is the fallback the backend uses on
Windows dev hosts.

Contract pinned here:
  * Only the pin name ``webgui.estop`` engages the ESTOP.
  * Any truthy write to ``webgui.estop`` triggers
    ``StateMachineMock.trigger_estop()`` (sets ``estop=1``,
    ``task_state=STATE_ESTOP``, ``interp_state=INTERP_IDLE``).
  * A 0-write does not trigger; it is the latch-clear that lets
    a future 1-write fire again.
  * Unrelated pins (e.g. ``webgui.spindle-forward``) are
    ignored by this component — they fall through to whatever
    owner is registered for them.
"""

from __future__ import annotations


from hardware.mock.HalMock import HalMock
from hardware.mock.MockEStopComponent import MockEStopComponent
from hardware.mock.StateMachineMock import StateMachineMock


def _fresh_stack() -> tuple[StateMachineMock, HalMock, MockEStopComponent]:
    """Build a fresh mock stack: state machine + HAL + ESTOP component.

    The state machine boots in STATE_ESTOP by default, so each test
    explicitly resets to STATE_ESTOP_RESET before driving the pin —
    this isolates the test from the singleton's prior state.
    """
    sm = StateMachineMock()
    sm.reset_estop()
    hal = HalMock(nml_state=sm)
    comp = MockEStopComponent(sm)
    hal.register_component(comp)
    return sm, hal, comp


class TestMockEStopComponent:
    """Pin-write contract for ``webgui.estop`` on the mock."""

    def test_truthy_write_triggers_estop(self):
        """The 0 -> 1 dance that ``EStopPin`` performs lands on
        STATE_ESTOP via ``trigger_estop()``.
        """
        sm, hal, _ = _fresh_stack()
        assert sm.estop == 0
        assert sm.task_state == sm.STATE_ESTOP_RESET

        hal.set_pin("webgui.estop", 0)
        assert sm.estop == 0  # 0-write is silent

        hal.set_pin("webgui.estop", 1)
        assert sm.estop == 1
        assert sm.task_state == sm.STATE_ESTOP
        assert sm.interp_state == sm.INTERP_IDLE

    def test_zero_write_does_not_trigger(self):
        """A standalone 0-write must not engage the ESTOP. The pin
        is reset to 0 first by the wrapper to clear the latch;
        firing here would mean a reset cycle re-engages ESTOP.
        """
        sm, hal, _ = _fresh_stack()
        hal.set_pin("webgui.estop", 0)
        assert sm.estop == 0
        assert sm.task_state == sm.STATE_ESTOP_RESET

    def test_repeated_truthy_writes_keep_estop_engaged(self):
        """A second 1-write without an intervening 0-write is
        idempotent — ESTOP stays engaged, no spurious error.
        """
        sm, hal, _ = _fresh_stack()
        hal.set_pin("webgui.estop", 1)
        hal.set_pin("webgui.estop", 1)
        assert sm.estop == 1
        assert sm.task_state == sm.STATE_ESTOP

    def test_unrelated_pins_are_ignored(self):
        """Only ``webgui.estop`` engages the ESTOP. Other pins
        that happen to be set on the same HAL must not trigger
        a state transition.
        """
        sm, hal, _ = _fresh_stack()
        # Drive pins that other components (heater, spindle, etc.)
        # would normally own. The MockEStopComponent must decline
        # them all — return False from set_pin so the broadcast
        # continues to the next registered component (or falls
        # through to the central pin dict).
        hal.set_pin("webgui.spindle-forward", 1)
        hal.set_pin("webgui.target-temperature", 100.0)
        hal.set_pin("webgui.some-future-pin", 1)
        assert sm.estop == 0
        assert sm.task_state == sm.STATE_ESTOP_RESET

    def test_read_pin_returns_current_estop_bit(self):
        """``read_pin`` returns the live ``estop`` bit so any
        consumer (debug panel, tests) sees a consistent value
        after a write.
        """
        sm, hal, _ = _fresh_stack()
        assert hal.get_pin("webgui.estop") == 0
        hal.set_pin("webgui.estop", 1)
        assert hal.get_pin("webgui.estop") == 1

    def test_read_pin_returns_none_for_unrelated_pin(self):
        """``read_pin`` must return ``None`` (not raise) for any
        pin the component does not own.
        """
        sm, hal, comp = _fresh_stack()
        assert hal.get_pin("webgui.spindle-forward") == 0.0
        # ``HalMock.get_pin`` returns the default (0.0) when no
        # component claims the pin, so the assertion above is the
        # observable contract; we also verify the component itself
        # declines to claim the pin.
        assert comp.read_pin("webgui.spindle-forward") is None

    def test_id_field_is_stable(self):
        """The ``id`` field is what ``HalMock.register_component``
        uses to dedup; the always-on component must expose a
        stable id so a duplicate registration replaces instead
        of stacking.
        """
        _, _, comp = _fresh_stack()
        assert comp.id == "estop"

    def test_full_activate_estop_path(self):
        """End-to-end: the service-side ``EStopPin.set_value(True)``
        0 -> 1 dance lands on STATE_ESTOP through the full
        component chain.
        """
        sm, hal, _ = _fresh_stack()

        # The pin wrapper does: set_value(0) ; sleep ; set_value(1)
        hal.set_pin("webgui.estop", 0)
        hal.set_pin("webgui.estop", 1)

        assert sm.estop == 1
        assert sm.task_state == sm.STATE_ESTOP

        # And a subsequent reset via the state machine clears it
        # for the next operator cycle.
        sm.reset_estop()
        assert sm.estop == 0
        assert sm.task_state == sm.STATE_ESTOP_RESET
