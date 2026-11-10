"""``PROBE_CALIBRATE`` / ``TESTZ`` / ``ACCEPT`` / ``ABORT`` (the paper test for
``[probe] z_offset``) and the probe offsets in ``probe_points``."""
from __future__ import annotations

import pytest

import services.ProbeCalibrateService as module
import services.Probing as probing
from exceptions import BadRequestError
from hardware.Connection import MachineState

TRIGGER_Z = 2.0


class Config:
    def __init__(self, probe=None):
        self.payload = {
            "probe": probe if probe is not None else {"pin": "PB6", "x_offset": -25.0, "y_offset": 10.0},
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
        self.position = [100.0, 100.0, 10.0, 0.0]
        self.actual_position = list(self.position)
        self.probed_position = [0.0, 0.0, 0.0, 0.0]
        self.probe_tripped = False
        self.interp_state = 1

    def poll(self):
        pass


@pytest.fixture
def rig(monkeypatch):
    stat = Stat()
    lines, events = [], []
    relative = {"on": False}

    def dispatch(line, ack_timeout=1.0):
        lines.append(line)
        if line == "G91":
            relative["on"] = True
        elif line == "G90":
            relative["on"] = False
        elif line.startswith("G38.2"):
            stat.probed_position = [stat.position[0], stat.position[1], TRIGGER_Z, 0.0]
            stat.position[2] = TRIGGER_Z
            stat.probe_tripped = True
        elif line.startswith("G53 G1 "):
            for word in line.split()[2:]:
                if word[0] in "XY":
                    stat.position["XY".index(word[0])] = float(word[1:])
        elif line.startswith("G0 ") and relative["on"]:
            for word in line.split()[1:]:
                stat.position["XYZ".index(word[0])] += float(word[1:])
        return None

    monkeypatch.setattr(probing, "dispatch_mdi", dispatch)
    monkeypatch.setattr(probing.MacroExecutionService, "_wait_until_idle", staticmethod(lambda stat, serial: None))

    class Console:
        def log_event(self, message, level=None, source=None):
            events.append((str(getattr(level, "value", level)), message))

    monkeypatch.setattr(module, "get_console_logger", lambda: Console())
    return type("R", (), {"stat": stat, "lines": lines, "events": events})


def test_start_puts_the_nozzle_over_the_probed_spot_at_the_trigger_height(rig):
    service = module.ProbeCalibrateService(Config())
    session = service.start(rig.stat)
    assert session.trigger_z == TRIGGER_Z
    assert rig.lines == ["G91", "G38.2 Z-11.9900 F300.0", "G0 Z5.0000", "G0 X-25.0000 Y10.0000", "G0 Z-5.0000",
                         "G90"]
    # the nozzle moved by the probe's offset: it is where the probe touched
    assert rig.stat.position[:3] == [75.0, 110.0, TRIGGER_Z]
    assert rig.events[-1][0] == "INFO" and "ACCEPT" in rig.events[-1][1]


def test_testz_and_accept_give_the_z_offset(rig):
    service = module.ProbeCalibrateService(Config())
    service.start(rig.stat)
    assert service.testz(rig.stat, -1.5) == pytest.approx(1.5)
    assert service.testz(rig.stat, -0.25) == pytest.approx(1.75)
    assert service.testz(rig.stat, 0.05) == pytest.approx(1.70)
    assert "z_offset 1.7000" in rig.events[-1][1]
    assert service.accept(rig.stat) == pytest.approx(1.70)
    level, text = rig.events[-1]
    assert level == "INFO" and "[probe] z_offset: 1.700" in text
    assert service.session is None and service.last_z_offset == pytest.approx(1.70)


def test_accept_refuses_a_nozzle_above_the_trigger_height(rig):
    service = module.ProbeCalibrateService(Config())
    service.start(rig.stat)
    service.testz(rig.stat, 0.5)
    assert service.accept(rig.stat) == pytest.approx(-0.5)
    assert rig.events[-1][0] == "ERROR"


def test_commands_without_a_session(rig, monkeypatch):
    monkeypatch.setattr(module, "get_stat_channel", lambda: rig.stat)
    service = module.ProbeCalibrateService(Config())
    with pytest.raises(BadRequestError):
        service.run_command("ACCEPT")
    with pytest.raises(BadRequestError):
        service.run_command("TESTZ Z=-0.1")
    assert service.run_command("ABORT") is False  # nothing of ours to abort
    assert service.run_command("G0 X1") is False


def test_testz_needs_a_sensible_step(rig, monkeypatch):
    monkeypatch.setattr(module, "get_stat_channel", lambda: rig.stat)
    service = module.ProbeCalibrateService(Config())
    service.start(rig.stat)
    for bad in ("TESTZ", "TESTZ Z=abc", "TESTZ Z=0", "TESTZ Z=-6"):
        with pytest.raises(BadRequestError):
            service.run_command(bad)
    assert service.run_command("abort")
    assert service.session is None


def test_mdi_runs_the_whole_test(rig, monkeypatch):
    monkeypatch.setattr(module, "get_stat_channel", lambda: rig.stat)
    service = module.ProbeCalibrateService(Config())
    assert service.run_command("PROBE_CALIBRATE SPEED=2")
    service.join(5)
    assert "G38.2 Z-11.9900 F120.0" in rig.lines
    assert service.run_command("TESTZ Z=-1.2")
    service.join(5)
    assert service.run_command("ACCEPT")
    assert service.last_z_offset == pytest.approx(1.2)


def test_needs_a_probe(rig):
    config = Config()
    config.payload["probe"] = None
    with pytest.raises(BadRequestError):
        module.ProbeCalibrateService(config).start(rig.stat)


def test_probe_points_moves_the_nozzle_by_the_offsets_and_subtracts_z_offset(rig):
    heights = probing.probe_points(
        rig.stat, [(50.0, 60.0)], safe_z=5.0, travel_mm_s=50.0, probe_mm_s=5.0, bottom=-2.0,
        offsets=probing.ProbeOffsets(-25.0, 10.0, 0.5),
    )
    assert "G53 G1 X75.0000 Y50.0000 F3000.0" in rig.lines  # the probe lands on X50 Y60
    assert heights == [pytest.approx(TRIGGER_Z - 0.5)]


def test_probe_offsets_from_payload():
    assert probing.ProbeOffsets.from_payload({}) == probing.ProbeOffsets()
    assert probing.ProbeOffsets.from_payload({"probe": {"x_offset": 1, "z_offset": 2.5}}) == \
        probing.ProbeOffsets(1.0, 0.0, 2.5)
