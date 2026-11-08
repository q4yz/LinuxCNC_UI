"""``ZTiltService``: probe, fit, correct, retry — against a simulated
tilted bed whose probed heights follow the applied motor offsets."""
from __future__ import annotations

import re

import pytest

import services.MacroExecutionService as macro_module
import services.ZTiltService as module
from core.z_tilt import fit_heights
from exceptions import BadRequestError
from hardware.Connection import MachineState

PIVOTS = [(-50.0, 18.0), (260.0, 18.0), (100.0, 250.0)]
POINTS = [(30.0, 5.0), (230.0, 5.0), (100.0, 200.0)]


def bed(x, y):
    """The tilted bed's height under the toolhead (mm)."""
    return 0.002 * x - 0.001 * y + 0.5


class FakeConfig:
    def __init__(self, **overrides):
        self.z_tilt = {
            "z_positions": [list(p) for p in PIVOTS], "points": [list(p) for p in POINTS],
            "joints": [2, 3, 4], "speed": 50, "horizontal_move_z": 5, "probe_speed": 5,
            "probe_min_z": 0, "retries": 3, "retry_tolerance": 0.001, "max_adjust": 5, **overrides,
        }

    def load_payload(self):
        return {"z_tilt": self.z_tilt}

    def get_axes(self):
        return [{"id": "x", "joint_numbers": [0]}, {"id": "y", "joint_numbers": [1]},
                {"id": "z", "joint_numbers": [2, 3, 4]}]


class Pin:
    def __init__(self):
        self.value = 0.0

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value


class FakeStat:
    def __init__(self):
        self.estop = False
        self.task_state = MachineState.ON.value
        self.task_mode = 3
        self.interp_state = 1
        self.homed = [1, 1, 1, 1, 1]
        self.probe_tripped = False
        self.probed_position = (0.0, 0.0, 0.0)

    def poll(self):
        pass


@pytest.fixture
def rig(monkeypatch):
    stat = FakeStat()
    lines: list[str] = []
    pins = [Pin() for _ in PIVOTS]
    position = {"x": 0.0, "y": 0.0}
    sign = {"value": 1.0}
    trigger = {"on": True}

    def dispatch_mdi(line, ack_timeout=1.0):
        lines.append(line)
        if m := re.search(r"X(-?[\d.]+) Y(-?[\d.]+)", line):
            position["x"], position["y"] = float(m.group(1)), float(m.group(2))
        if "G38.2" in line:
            # Raising a motor's joint by d lowers the probed height there by d.
            correction = fit_heights(PIVOTS, [sign["value"] * p.value for p in pins],
                                     [(position["x"], position["y"])])[0]
            stat.probe_tripped = trigger["on"]
            stat.probed_position = (position["x"], position["y"], bed(position["x"], position["y"]) - correction)
        return None

    monkeypatch.setattr(module, "dispatch_mdi", dispatch_mdi)
    monkeypatch.setattr(module, "read_hal_pin", lambda name: pins[int(name.rsplit("-", 1)[1].split(".")[0])].value)
    monkeypatch.setattr(macro_module, "_IDLE_POLL_S", 0)
    events: list[str] = []

    class Console:
        def log_event(self, message, level=None, source=None):
            events.append(message)

    monkeypatch.setattr(module, "get_console_logger", lambda: Console())

    def service(**overrides):
        s = module.ZTiltService(config=FakeConfig(**overrides))
        s._pins = pins
        return s

    return type("R", (), {"stat": stat, "lines": lines, "pins": pins, "events": events,
                          "service": staticmethod(service), "sign": sign, "trigger": trigger})


def test_levels_the_bed(rig):
    offsets = rig.service().run(rig.stat)
    # One correction levels a plane exactly; the second round confirms it.
    assert rig.events[-1].startswith("Z tilt adjust done: within")
    heights = [bed(*p) - fit_heights(PIVOTS, offsets, [p])[0] for p in POINTS]
    assert max(heights) - min(heights) < 1e-9
    assert abs(sum(offsets)) < 1e-9  # mean Z kept
    # The motor under the high corner went up.
    high = max(range(3), key=lambda k: bed(*PIVOTS[k]))
    assert offsets[high] == max(offsets)


def test_probe_moves(rig):
    rig.service(retries=0).run(rig.stat)
    assert rig.lines[:5] == ["G90", "G53 G0 Z5.0000", "G53 G1 X30.0000 Y5.0000 F3000.0",
                             "G53 G38.2 Z0.0000 F300.0", "G53 G0 Z5.0000"]
    assert sum("G38.2" in line for line in rig.lines) == 3  # retries 0: one round


def test_wrong_pivot_order_is_caught(rig):
    rig.sign["value"] = -1.0  # corrections make it worse
    with pytest.raises(module.ZTiltError, match="spread grew"):
        rig.service().run(rig.stat)


def test_probe_not_triggering(rig):
    rig.trigger["on"] = False
    with pytest.raises(module.ZTiltError, match="did not trigger"):
        rig.service().run(rig.stat)


def test_max_adjust(rig):
    with pytest.raises(module.ZTiltError, match="max_adjust"):
        rig.service(max_adjust=0.01).run(rig.stat)


def test_needs_xyz_homed(rig):
    rig.stat.homed = [1, 1, 0, 1, 1]
    with pytest.raises(BadRequestError, match="joint\\(s\\) 2"):
        rig.service().run(rig.stat)


def test_macro_line_runs_it(rig, monkeypatch):
    service = rig.service(retries=0)
    monkeypatch.setattr(module, "get_z_tilt_service", lambda: service)
    assert macro_module.MacroExecutionService._z_tilt("level", rig.stat) is True
    rig.trigger["on"] = False
    assert macro_module.MacroExecutionService._z_tilt("level", rig.stat) is False
