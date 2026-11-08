"""A converted print's G28 / G29 (``; LINUXCNC_UI_PRESTART:``) run before
the program starts (`PrintStartService`), and MDI ``G28`` / ``G29``."""
from __future__ import annotations

import pytest

import services.PrintStartService as module
from core.gcode_converter import convert


class Recorder:
    def __init__(self):
        self.calls: list = []


@pytest.fixture
def rig(monkeypatch, tmp_path):
    rec = Recorder()
    events: list = []

    class Homing:
        def is_running(self): return False
        def run_blocking(self, stat):
            rec.calls.append("home")
            return rec.home_reason if hasattr(rec, "home_reason") else None
        def require_homed(self): rec.calls.append("guard")

    class ZTilt:
        configured = True
        def settings(self): return {} if self.configured else None
        def run(self, stat): rec.calls.append("z_tilt")

    homing, z_tilt = Homing(), ZTilt()
    import services.HomingRoutineService as homing_module
    import services.LevelingService as leveling
    monkeypatch.setattr(homing_module, "get_homing_routine_service", lambda: homing)

    def level(stat):
        if not z_tilt.configured:
            events.append("G29 skipped: this machine has no [z_tilt] and no [bed_mesh].")
            return None
        rec.calls.append("z_tilt")
        return None

    monkeypatch.setattr(leveling, "level", level)
    monkeypatch.setattr(module, "get_stat_channel", lambda: object())
    monkeypatch.setattr(module, "execute_sync_cmd", lambda name, timeout=0, *a: rec.calls.append((name, *a)))
    class Console:
        def log_event(self, message, level=None, source=None): events.append(message)

    monkeypatch.setattr(module, "get_console_logger", lambda: Console())
    rec.events, rec.z_tilt = events, z_tilt
    return rec


def _start(steps):
    service = module.PrintStartService()
    service.start(steps)
    service.join(5)


def test_home_level_then_run(rig):
    _start(["home", "level"])
    assert rig.calls[:3] == ["home", "z_tilt", "guard"]
    assert rig.calls[3][0] == "mode" and rig.calls[4][0] == "auto"


def test_level_without_z_tilt_is_skipped(rig):
    rig.z_tilt.configured = False
    _start(["home", "level"])
    assert "z_tilt" not in rig.calls and any(c[0] == "auto" for c in rig.calls if isinstance(c, tuple))
    assert any("no [z_tilt]" in e for e in rig.events)


def test_failed_homing_does_not_start_the_program(rig):
    rig.home_reason = "joint 0 did not home"
    _start(["home"])
    assert not any(isinstance(c, tuple) and c[0] == "auto" for c in rig.calls)
    assert rig.events[-1].startswith("Print not started: homing")


def test_prestart_steps_read_from_the_file(tmp_path):
    path = tmp_path / "print.ngc"
    path.write_text(convert("G28\nG29\nG1 X1 Y1 E1\n").text)
    assert module.prestart_steps(str(path)) == ["home", "level"]
    plain = tmp_path / "part.ngc"
    plain.write_text("G0 X1\nM2\n")
    assert module.prestart_steps(str(plain)) == []
    assert module.prestart_steps(str(tmp_path / "missing.ngc")) == []


def test_mdi_g28_runs_the_homing(monkeypatch):
    import services.HomingRoutineService as homing_module
    from services.StateService import StateService

    started = []

    class Homing:
        def __init__(self, override): self._override = override
        def override(self): return self._override
        def applies_to(self, axis): return self._override is not None and axis in "xyz"
        def is_running(self): return False
        def start(self, steps=None): started.append(None if steps is None else [s.axes for s in steps])

    monkeypatch.setattr(homing_module, "get_homing_routine_service", lambda: Homing({"gcode": "G28"}))
    assert StateService._ui_command("G28") and StateService._ui_command("g28 z")
    assert started == [None, None]  # the routine
    monkeypatch.setattr(homing_module, "get_homing_routine_service", lambda: Homing(None))
    assert StateService._ui_command("G28 X")
    assert started[-1] == [("X",)]  # no routine: home X directly
    assert not StateService._ui_command("G28.1") and not StateService._ui_command("G0 X1")
