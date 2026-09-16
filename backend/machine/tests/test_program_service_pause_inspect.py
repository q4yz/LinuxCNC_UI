"""``ProgramService`` — Pause & Inspect (Z-axis lift + spindle inhibit).

Replaces the old "pause stops every spindle via MDI" behaviour
(deleted `test_program_service_pause_spindle.py`): a plain Pause now
only halts motion (`AUTO_PAUSE`), and lifting the tool clear of the
work / inhibiting the spindle is a separate, explicit operator action
(`pause_inspect`) driven through HAL `eoffset`/`spindle-inhibit` pins
so the trajectory planner stays in sync — not an M5-via-MDI spindle
stop.

Unit-level: swaps in a `MagicMock` pin object (same pattern as
`test_machine_state_facade.py`'s `activate_estop` tests) rather than
standing up the real HAL mock stack, since the only thing under test
is the pin-write sequencing/timing itself.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, call

import pytest

from dtos.PauseInspect import PauseInspectPin
from services.ProgramService import ProgramService


def _service_with_fake_pins() -> tuple[ProgramService, MagicMock, MagicMock]:
    service = ProgramService()
    z_lift = MagicMock()
    spindle_inhibit = MagicMock()
    service._PauseInspect = PauseInspectPin("pause_inspect", z_lift, spindle_inhibit)
    return service, z_lift, spindle_inhibit


@pytest.fixture(autouse=True)
def _no_real_hardware_dispatch(monkeypatch):
    monkeypatch.setattr("services.ProgramService.execute_sync_cmd", lambda *a, **k: None)


def test_pause_program_no_longer_touches_the_spindle():
    """A plain Pause is `AUTO_PAUSE` only now — Pause & Inspect is a
    separate, explicit action (see module docstring)."""
    service, z_lift, spindle_inhibit = _service_with_fake_pins()

    service.pause_program()

    assert z_lift.set_value.call_count == 0
    assert spindle_inhibit.set_value.call_count == 0


def test_pause_inspect_engages_both_pins():
    service, z_lift, spindle_inhibit = _service_with_fake_pins()

    service.pause_inspect()

    assert z_lift.set_value.call_args_list == [call(True)]
    assert spindle_inhibit.set_value.call_args_list == [call(True)]


def test_pause_inspect_lazily_initializes_pins_when_not_preloaded():
    """`preload_hal_pins()` isn't guaranteed to have run yet (e.g. a
    fresh instance outside the app's startup sequence) — must not
    raise `AttributeError`."""
    service = ProgramService()
    assert service._PauseInspect is None

    service.pause_inspect()  # must not raise

    assert service._PauseInspect is not None


def test_resume_program_clears_spindle_inhibit_before_z_lift(monkeypatch):
    """Spindle inhibit releases first and gets 2.5s to spin back up
    before the Z lift retracts, so the tool never re-enters the cut
    before the spindle is at speed."""
    service, z_lift, spindle_inhibit = _service_with_fake_pins()

    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("services.ProgramService.asyncio.sleep", fake_sleep)

    asyncio.run(service.resume_program())

    assert spindle_inhibit.set_value.call_args_list == [call(False)]
    assert z_lift.set_value.call_args_list == [call(False)]
    assert sleeps == [2.5, 0.5]


def test_resume_program_dispatches_auto_resume_after_clearing_pins(monkeypatch):
    service, _, _ = _service_with_fake_pins()

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr("services.ProgramService.asyncio.sleep", fake_sleep)

    calls = []
    monkeypatch.setattr(
        "services.ProgramService.execute_sync_cmd",
        lambda *a, **k: calls.append(a),
    )

    asyncio.run(service.resume_program())

    assert calls, "execute_sync_cmd must be dispatched to resume motion"
    assert calls[0][0] == "auto"


def test_resume_program_lazily_initializes_pins_when_not_preloaded(monkeypatch):
    service = ProgramService()
    assert service._PauseInspect is None

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr("services.ProgramService.asyncio.sleep", fake_sleep)

    asyncio.run(service.resume_program())  # must not raise

    assert service._PauseInspect is not None
