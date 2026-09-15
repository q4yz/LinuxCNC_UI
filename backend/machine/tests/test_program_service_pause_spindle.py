"""``ProgramService.pause_program`` — stop every digital spindle on pause.

LinuxCNC itself never does this on its own: ``AUTO_PAUSE`` only halts
motion, the spindle keeps turning. This operator wants a running
program's PAUSE button to also kill the spindle, reusing the exact
same M5-via-MDI path (``SpindleDigitalService.set_spindle``) every
other spindle stop in this app already goes through.

Unit-level: monkeypatches ``ProgramService``'s own imported names
(``get_tools_service`` / ``get_spindle_digital_service``) with fakes
rather than standing up the full HAL mock machinery, since the only
thing under test is the enumerate-and-stop logic itself.
"""

from __future__ import annotations

import pytest

from dtos.tools.SpindleDigitalDto import DirectionStateType, SpindleDigitalPins
from services.ProgramService import ProgramService


class _FakeHeaterPins:
    """A non-spindle tool — must be ignored, not stopped."""

    id = "heater_bed"


class _FakeToolsService:
    def __init__(self, pins):
        self._pins = pins

    def get_halpins(self):
        return self._pins


class _FakeSpindleDigitalService:
    def __init__(self):
        self.calls = []
        self.raise_for = set()

    def set_spindle(self, dto):
        if dto.id in self.raise_for:
            raise RuntimeError(f"boom: {dto.id}")
        self.calls.append(dto)


@pytest.fixture(autouse=True)
def _no_real_hardware_dispatch(monkeypatch):
    """``pause_program`` also calls ``execute_sync_cmd`` for AUTO_PAUSE
    itself — stub it out so these tests exercise only the spindle-stop
    addition, not the mock hardware layer's own AUTO_PAUSE handling."""
    monkeypatch.setattr("services.ProgramService.execute_sync_cmd", lambda *a, **k: None)


def test_pause_stops_every_configured_digital_spindle(monkeypatch):
    fake_tools = _FakeToolsService([SpindleDigitalPins(id="spindle_0")])
    fake_spindle = _FakeSpindleDigitalService()
    monkeypatch.setattr("services.ProgramService.get_tools_service", lambda: fake_tools)
    monkeypatch.setattr("services.ProgramService.get_spindle_digital_service", lambda: fake_spindle)

    ProgramService().pause_program()

    assert len(fake_spindle.calls) == 1
    assert fake_spindle.calls[0].id == "spindle_0"
    assert fake_spindle.calls[0].state == DirectionStateType.STOP


def test_pause_stops_every_spindle_when_more_than_one_is_configured(monkeypatch):
    fake_tools = _FakeToolsService(
        [SpindleDigitalPins(id="spindle_0"), SpindleDigitalPins(id="spindle_1")]
    )
    fake_spindle = _FakeSpindleDigitalService()
    monkeypatch.setattr("services.ProgramService.get_tools_service", lambda: fake_tools)
    monkeypatch.setattr("services.ProgramService.get_spindle_digital_service", lambda: fake_spindle)

    ProgramService().pause_program()

    assert {dto.id for dto in fake_spindle.calls} == {"spindle_0", "spindle_1"}


def test_pause_ignores_non_spindle_tools(monkeypatch):
    fake_tools = _FakeToolsService([_FakeHeaterPins()])
    fake_spindle = _FakeSpindleDigitalService()
    monkeypatch.setattr("services.ProgramService.get_tools_service", lambda: fake_tools)
    monkeypatch.setattr("services.ProgramService.get_spindle_digital_service", lambda: fake_spindle)

    ProgramService().pause_program()

    assert fake_spindle.calls == []


def test_pause_with_no_tools_configured_does_not_crash(monkeypatch):
    fake_tools = _FakeToolsService([])
    fake_spindle = _FakeSpindleDigitalService()
    monkeypatch.setattr("services.ProgramService.get_tools_service", lambda: fake_tools)
    monkeypatch.setattr("services.ProgramService.get_spindle_digital_service", lambda: fake_spindle)

    ProgramService().pause_program()  # must not raise

    assert fake_spindle.calls == []


def test_a_spindle_stop_failure_does_not_fail_the_pause(monkeypatch):
    """Motion has already stopped by the time the spindle-stop runs —
    a failure stopping the spindle must be logged, not raised, so the
    pause itself is never reported as failed because of it."""
    fake_tools = _FakeToolsService(
        [SpindleDigitalPins(id="spindle_0"), SpindleDigitalPins(id="spindle_1")]
    )
    fake_spindle = _FakeSpindleDigitalService()
    fake_spindle.raise_for = {"spindle_0"}
    monkeypatch.setattr("services.ProgramService.get_tools_service", lambda: fake_tools)
    monkeypatch.setattr("services.ProgramService.get_spindle_digital_service", lambda: fake_spindle)

    ProgramService().pause_program()  # must not raise despite spindle_0 failing

    # spindle_1 must still be attempted even though spindle_0 raised.
    assert [dto.id for dto in fake_spindle.calls] == ["spindle_1"]
