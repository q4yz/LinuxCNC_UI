"""``PROBE_ACCURACY``: probe the same spot SAMPLES times, samples under
DEBUG, max / min / range / average / median / standard deviation under INFO."""
from __future__ import annotations

import statistics

import pytest

import services.motion.ProbeAccuracyService as module
import services.motion.Probing as probing
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
        elif line.startswith("G53 G0 Z"):
            stat.actual_position[2] = stat.position[2] = float(line[8:])
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


def test_probe_moves_relative_retracts_absolute(rig):
    module.ProbeAccuracyService(Config()).run(rig.stat, module.ProbeAccuracyRequest(samples=2, retract=2.0))
    assert rig.lines[:3] == ["G90", "G91", "G38.2 Z-6.9900 F300.0"]  # from Z5 down to 0.01 above position_min -2
    assert rig.lines[-1] == "G90"
    # LinuxCNC takes G53 with G0 / G1 only: never on the probe move itself
    assert not any(l.startswith("G53") and "G38" in l for l in rig.lines)
    # back up to an absolute height: the trigger point + the retract
    assert f"G53 G0 Z{TRIGGERS[0] + 2.0:.4f}" in rig.lines
    # the next probe starts from that known height, not from a read-back position
    assert f"G38.2 Z-{module.probe_distance(TRIGGERS[0] + 2.0, -2.0):.4f} F300.0" in rig.lines


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


# -- a probe like the real one: hysteresis, overshoot, the probing-move gate --


class Probe:
    """Triggers at ``trigger`` on the way down, releases only at
    ``trigger + hysteresis``; the machine stops ``overshoot`` past the
    trigger. ``motion.probe-input`` sees it only during a G38 move, so a
    probe still triggered "trips" the instant the move starts."""

    def __init__(self, stat, trigger=2.794, hysteresis=1.91, overshoot=0.09, readable=True):
        self.stat, self.trigger, self.hysteresis, self.overshoot = stat, trigger, hysteresis, overshoot
        self.readable = readable
        self.triggered = False

    def move_to(self, z):
        self.stat.position[2] = self.stat.actual_position[2] = z
        if z >= self.trigger + self.hysteresis:
            self.triggered = False

    def dispatch(self, line, ack_timeout=1.0):
        z = self.stat.position[2]
        if line.startswith("G38.2"):
            if self.triggered:  # still triggered: trips at once, at the start
                self.stat.probed_position[2] = z
            else:
                self.stat.probed_position[2] = self.trigger
                self.move_to(self.trigger - self.overshoot)
                self.triggered = True
            self.stat.probe_tripped = True
        elif line.startswith("G53 G0 Z"):
            self.move_to(float(line[8:]))
        return None

    def signal(self):
        return self.triggered if self.readable else None


@pytest.fixture
def real(monkeypatch):
    stat = Stat()
    stat.position[2] = stat.actual_position[2] = 8.0
    probe = Probe(stat)
    events = []
    monkeypatch.setattr(probing, "dispatch_mdi", probe.dispatch)
    monkeypatch.setattr(probing.MacroExecutionService, "_wait_until_idle", staticmethod(lambda stat, serial: None))
    monkeypatch.setattr(probing, "probe_triggered", probe.signal)
    monkeypatch.setattr(probing, "RELEASE_WAIT_S", 0.0)

    class Console:
        def log_event(self, message, level=None, source=None):
            events.append((str(getattr(level, "value", level)), message))

    monkeypatch.setattr(module, "get_console_logger", lambda: Console())
    return type("R", (), {"stat": stat, "probe": probe, "events": events})


def run(real, **kw):
    return module.ProbeAccuracyService(Config()).run(real.stat, module.ProbeAccuracyRequest(**{"samples": 10, **kw}))


def test_the_reported_bug_no_longer_alternates(real):
    """1.91 mm hysteresis, 0.09 mm overshoot, 2 mm retract: the samples
    alternated 2.79 / 4.70 (every other probe tripped at its start)."""
    result = run(real, retract=2.0)
    assert result.samples == [pytest.approx(2.794)] * 10
    assert result.range == pytest.approx(0.0)


def test_a_probe_releasing_above_the_retract_gets_backed_up_further(real):
    real.probe.hysteresis = 3.5
    result = run(real, retract=2.0)
    assert result.samples == [pytest.approx(2.794)] * 10
    warnings = [m for lvl, m in real.events if lvl == "WARNING"]
    assert len(warnings) == 1 and "SAMPLE_RETRACT_DIST=4" in warnings[0]


def test_an_unreadable_signal_still_catches_a_trip_at_the_start(real):
    real.probe.readable = False
    real.probe.hysteresis = 3.5
    with pytest.raises(module.ProbeAccuracyError, match="triggered at its start"):
        run(real, retract=2.0)


def test_a_probe_that_never_releases_stops_the_test(real):
    real.probe.hysteresis = 100.0
    with pytest.raises(module.ProbeAccuracyError, match="still triggered"):
        run(real, retract=2.0)


def test_bed_mesh_probing_refuses_a_still_triggered_probe(monkeypatch):
    monkeypatch.setattr(probing, "dispatch_mdi", lambda line, ack_timeout=1.0: None)
    monkeypatch.setattr(probing.MacroExecutionService, "_wait_until_idle", staticmethod(lambda stat, serial: None))
    monkeypatch.setattr(probing, "probe_triggered", lambda: True)
    monkeypatch.setattr(probing, "RELEASE_WAIT_S", 0.0)
    with pytest.raises(probing.ProbeError, match="still triggered"):
        probing.probe_points(Stat(), [(10.0, 10.0)], safe_z=5.0, travel_mm_s=50, probe_mm_s=5, bottom=-2.0)
