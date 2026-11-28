"""A slicer job that powers the machine on and off (`JobPowerService`)."""
from __future__ import annotations

import pytest

import services.program.JobPowerService as module
from exceptions import ConflictError

ESTOP, OFF, ON = 1, 3, 4


class Rig:
    def __init__(self, monkeypatch, state=ESTOP, start_error=None):
        self.state = state
        self.busy_reads: list = []
        self.cmds: list = []
        rig = self

        def execute(name, timeout, *args):
            rig.cmds.append((name, *args))
            if name == "state":
                rig.state = args[0]

        class State:
            def reset_estop(self):
                rig.cmds.append(("reset_estop",))
                rig.state = OFF

        class Program:
            def start_program(self, line):
                rig.cmds.append(("start", line))
                if start_error:
                    raise start_error

        monkeypatch.setattr(module, "execute_sync_cmd", execute)
        monkeypatch.setattr(module, "_console", lambda *a, **k: None)
        import services.machine.StateService as state_mod
        import services.program.ProgramService as program_mod
        monkeypatch.setattr(state_mod, "get_state_service", lambda: State())
        monkeypatch.setattr(program_mod, "get_program_lifecycle_service", lambda: Program())
        self.service = module.JobPowerService(busy=self._busy, task_state=lambda: rig.state)
        self.service.POLL_S = 0.001
        self.service.END_SETTLE_S = 0.01
        self.service.START_SEEN_TIMEOUT_S = 0.2
        self.running = 5  # polls the job shows as busy

    def _busy(self):
        if self.running > 0:
            self.running -= 1
            return True
        return False


def test_releases_estop_powers_on_runs_and_powers_off(monkeypatch):
    rig = Rig(monkeypatch)
    rig.service.run_powered()
    rig.service.join(2)
    assert rig.cmds == [("reset_estop",), ("state", ON), ("start", 0), ("state", OFF)]
    assert rig.state == OFF


def test_already_on_still_powers_off_when_done(monkeypatch):
    rig = Rig(monkeypatch, state=ON)
    rig.service.run_powered()
    rig.service.join(2)
    assert rig.cmds == [("start", 0), ("state", OFF)]


def test_a_job_that_does_not_start_powers_off_again(monkeypatch):
    rig = Rig(monkeypatch, start_error=RuntimeError("No program loaded."))
    with pytest.raises(RuntimeError):
        rig.service.run_powered()
    assert rig.cmds[-1] == ("state", OFF)


def test_estop_during_the_job_is_left_alone(monkeypatch):
    rig = Rig(monkeypatch, state=ON)
    rig.service.run_powered()
    rig.state = ESTOP  # pressed while it ran
    rig.service.join(2)
    assert ("state", OFF) not in rig.cmds


def test_estop_that_does_not_release_refuses(monkeypatch):
    rig = Rig(monkeypatch)

    class Stuck:
        def reset_estop(self):
            raise ConflictError("E-stop reset did not hold")

    import services.machine.StateService as state_mod
    monkeypatch.setattr(state_mod, "get_state_service", lambda: Stuck())
    with pytest.raises(ConflictError):
        rig.service.run_powered()
    assert ("start", 0) not in rig.cmds
