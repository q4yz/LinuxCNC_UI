"""``PROBE_ACCURACY``: probe the same spot SAMPLES times, samples under
DEBUG, max / min / range / average / median / standard deviation under INFO."""
from __future__ import annotations

import statistics

import pytest

import services.ProbeAccuracyService as module
import services.Probing as probing
from exceptions import BadRequestError
from hardware.Connection import MachineState

TRIGGERS = [0.012, 0.010, 0.011, 0.013, 0.010]


class Config:
    def __init__(self, probe=True):
        self.payload = {
            "probe": {"pin": "PB6"} if probe else None,
            "axes": [{"id": "z", "joint_numbers": [2], "position_min": -2.0}],
        }

    def load_payload(self):
        return self.payload

    def get_axes(self):
        return self.payload["axes"]


class Stat:
    def __init__(self):
        self.estop = False
        self.task_state = MachineState.ON.value
        self.homed = [1, 1, 1]
        self.position = [0.0, 0.0, 5.0, 0.0]
        # feedback quantised to steps: a hair above the commanded position
        self.actual_position = [0.0, 0.0, 5.00006, 0.0]
        self.probed_position = [0.0, 0.0, 0.0, 0.0]
        self.probe_tripped = False
        self.interp_state = 1

    def poll(self):
        pass


@pytest.fixture
def rig(monkeypatch):
    stat = Stat()
    lines, events = [], []
    triggers = iter(TRIGGERS)
    relative = {"on": False}

    def dispatch(line, ack_timeout=1.0):
        lines.append(line)
        if line == "G91":
            relative["on"] = True
        elif line == "G90":
            relative["on"] = False
        elif line.startswith("G38.2"):
            z = next(triggers)
            stat.probed_position[2] = z
            stat.actual_position[2] = z
            stat.position[2] = z
            stat.probe_tripped = True
        elif line.startswith("G0 Z") and relative["on"]:
            stat.actual_position[2] += float(line[4:])
            stat.position[2] += float(line[4:])
        return None

    monkeypatch.setattr(probing, "dispatch_mdi", dispatch)
    monkeypatch.setattr(probing.MacroExecutionService, "_wait_until_idle", staticmethod(lambda stat, serial: None))

    class Console:
        def log_event(self, message, level=None, source=None):
            events.append((str(getattr(level, "value", level)), message))

    monkeypatch.setattr(module, "get_console_logger", lambda: Console())
    return type("R", (), {"stat": stat, "lines": lines, "events": events})


def test_statistics_and_log_levels(rig):
    result = module.ProbeAccuracyService(Config()).run(rig.stat, module.ProbeAccuracyRequest(samples=5))
    assert result.samples == TRIGGERS
    assert result.range == pytest.approx(0.003)
    assert result.average == pytest.approx(statistics.fmean(TRIGGERS))
    assert result.median == pytest.approx(0.011)
    assert result.stddev == pytest.approx(statistics.pstdev(TRIGGERS))
    level, summary = rig.events[-1]
    assert level == "INFO" and "standard deviation" in summary and "range 0.003000" in summary
    assert {lvl for lvl, _ in rig.events[:-1]} == {"DEBUG"}
    assert sum(": sample " in m for _, m in rig.events) == 5


def test_relative_probe_moves_never_g53(rig):
    module.ProbeAccuracyService(Config()).run(rig.stat, module.ProbeAccuracyRequest(samples=2, retract=2.0))
    assert rig.lines[0] == "G91" and rig.lines[-1] == "G90"
    assert rig.lines[1] == "G38.2 Z-6.9900 F300.0"  # from Z5 down to 0.01 above position_min -2
    assert "G0 Z2.0000" in rig.lines
    assert not any(l.startswith("G53") for l in rig.lines)


def test_parse_command():
    assert module.parse_command("G0 X1") is None
    assert module.parse_command("PROBE_ACCURACY") == module.ProbeAccuracyRequest()
    req = module.parse_command("probe_accuracy SAMPLES=20 SAMPLE_RETRACT_DIST=1.5 PROBE_SPEED=3")
    assert req == module.ProbeAccuracyRequest(samples=20, retract=1.5, speed=3.0)
    with pytest.raises(BadRequestError):
        module.parse_command("PROBE_ACCURACY SAMPLES=0")


def test_needs_a_probe_and_z_homed(rig):
    with pytest.raises(BadRequestError, match="probe"):
        module.ProbeAccuracyService(Config(probe=False)).run(rig.stat, module.ProbeAccuracyRequest())
    rig.stat.homed = [1, 1, 0]
    with pytest.raises(BadRequestError, match="Home Z"):
        module.ProbeAccuracyService(Config()).run(rig.stat, module.ProbeAccuracyRequest())


def test_probe_distance_never_reaches_the_limit():
    # the feedback position put the target past the soft limit
    # ("Probe move would exceed Z's negative limit")
    assert probing.probe_distance(5.00006, -2.0) == 6.99
    assert probing.probe_distance(5.0, -2.0) == 6.99
    assert probing.probe_distance(-1.995, -2.0) == 0.0
