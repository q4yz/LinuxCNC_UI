"""Two-pass probing and the board's probe latch (services.motion.Probing)."""
from __future__ import annotations

import re

import pytest
import services.motion.Probing as probing
from services.motion.Probing import (
    ProbeError,
    ProbeLatch,
    ProbeSettings,
    decode_latch,
    probe_down,
)

BED = 2.0  # where the probe really triggers
SCALE = 400.0  # Z steps per mm


class Stat:
    def __init__(self) -> None:
        self.probe_tripped = False
        self.probed_position = [0.0, 0.0, 0.0]
        self.actual_position = [0.0, 0.0, 10.0]
        self.joint_actual_position = [0.0, 0.0, 10.0 - 0.25]  # axis = joint + 0.25 (an external offset)
        self.interp_state = 1

    def poll(self) -> None:
        pass


@pytest.fixture
def rig(monkeypatch):
    stat = Stat()
    lines: list[str] = []
    latch = {"value": 0.0, "captures": 0}
    released = {"after": 0}

    def dispatch(line, ack_timeout=1.0):
        lines.append(line)
        if line.startswith("G38.2"):
            speed = float(re.search(r"F([\d.]+)", line).group(1)) / 60.0
            # LinuxCNC's sample: late by ~2 ms of travel; the board's latch: exact
            stat.probed_position = [0.0, 0.0, round(BED - speed * 0.002, 4)]
            stat.probe_tripped = True
            stat.actual_position[2] = BED - 0.05  # stopped below it
            stat.joint_actual_position[2] = stat.actual_position[2] - 0.25
            latch["captures"] = (latch["captures"] + 1) & 3
            count = round((BED - 0.25) * SCALE)
            latch["value"] = float(count * 4 + latch["captures"])
        elif line.startswith("G53 G0 Z"):
            stat.actual_position[2] = float(line.split("Z")[1])

    def read(name):
        if name == probing.PROBE_SIGNAL:
            if released["after"] > 0:
                released["after"] -= 1
                return True
            return False
        return None

    monkeypatch.setattr(probing, "dispatch_mdi", dispatch)
    monkeypatch.setattr(probing, "RELEASE_WAIT_S", 0.0)  # one reading per release check
    monkeypatch.setattr(probing.MacroExecutionService, "_wait_until_idle", staticmethod(lambda stat, serial: None))
    monkeypatch.setattr("hardware.Connection.read_hal_pin", read)
    return type("R", (), {"stat": stat, "lines": lines, "latch": latch, "released": released})


def test_the_latch_value_decodes_like_the_firmware_packs_it():
    for count, captures in [(0, 0), (1234, 1), (-5, 3), (-4194303, 2), (4194303, 1)]:
        assert decode_latch(float(count * 4 + captures)) == (count, captures)
    assert decode_latch(None) is None


def test_two_passes_fast_then_slow_from_above_the_first_trigger(rig):
    reading = probe_down(rig.stat, 10.0, -2.0, 5.0)
    assert reading.passes == 2 and not reading.latched
    assert reading.first_z == pytest.approx(BED - 5.0 * 0.002)
    assert reading.z == pytest.approx(BED - 1.0 * 0.002)  # the slow pass: a fifth of the error
    probes = [line for line in rig.lines if line.startswith("G38.2")]
    assert probes[0].endswith("F300.0") and probes[1].endswith("F60.0")
    start = reading.first_z + 1.0
    assert f"G53 G0 Z{start:.4f}" in rig.lines
    # the slow pass is limited to 1 mm below the first trigger
    assert probes[1].startswith(f"G38.2 Z-{probing.probe_distance(start, reading.first_z - 1.0):.4f}")


def test_one_pass_when_second_speed_is_0_or_not_slower(rig):
    assert probe_down(rig.stat, 10.0, -2.0, 5.0, settings=ProbeSettings(second_speed=0)).passes == 1
    assert probe_down(rig.stat, 10.0, -2.0, 1.0, settings=ProbeSettings(second_speed=1.0)).passes == 1


def test_a_probe_still_triggered_after_the_retract_is_lifted_further(rig):
    rig.released["after"] = 2  # two checks still triggered
    probe_down(rig.stat, 10.0, -2.0, 5.0)
    lifts = [line for line in rig.lines if line.startswith("G53 G0 Z")]
    assert len(lifts) == 3  # retract, +0.5, +0.5
    rig.released["after"] = 1000
    with pytest.raises(ProbeError, match="second_retract"):
        probe_down(rig.stat, 10.0, -2.0, 5.0)


def test_the_latched_height_replaces_linuxcnc_s_sample(rig):
    latch = ProbeLatch(joint=2, scale=SCALE, read=lambda name: rig.latch["value"])
    reading = probe_down(rig.stat, 10.0, -2.0, 5.0, latch=latch)
    assert reading.latched and reading.z == pytest.approx(BED, abs=1 / SCALE)
    assert reading.first_z == pytest.approx(BED, abs=1 / SCALE)


def test_the_latch_is_ignored_without_a_new_capture_or_when_it_disagrees(rig):
    frozen = ProbeLatch(joint=2, scale=SCALE, read=lambda name: 4.0 * 100)  # never captures
    assert not probe_down(rig.stat, 10.0, -2.0, 5.0, latch=frozen).latched
    wrong_scale = ProbeLatch(joint=2, scale=SCALE * 2, read=lambda name: rig.latch["value"])  # ~0.9 mm off
    reading = probe_down(rig.stat, 10.0, -2.0, 5.0, latch=wrong_scale)
    assert not reading.latched and reading.z == pytest.approx(BED - 0.002)
    no_scale = ProbeLatch(joint=2, scale=None, read=lambda name: rig.latch["value"])
    assert no_scale.captures() is None


def test_settings_from_the_payload():
    assert ProbeSettings.from_payload({}) == ProbeSettings(1.0, 1.0)
    assert ProbeSettings.from_payload({"probe": {"second_speed": 0, "second_retract": 2}}) == ProbeSettings(0.0, 2.0)
