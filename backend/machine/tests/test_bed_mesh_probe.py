"""``BedMeshProbeService`` (BED_MESH_CALIBRATE) and ``LevelingService``
(G29): probing a grid, the saved / activated mesh, compensation off
while probing."""
from __future__ import annotations

import re

import pytest

import services.BedMeshProbeService as module
import services.MacroExecutionService as macro_module
import services.Probing as probing
from exceptions import BadRequestError
from hardware.Connection import MachineState

MESH = {"probe_count": [3, 2], "mesh_min": [10, 20], "mesh_max": [110, 120], "speed": 100,
        "horizontal_move_z": 3, "probe_speed": 2, "probe_min_z": -1, "zero_reference_position": None}


def bed(x, y):
    return 0.001 * x + 0.002 * y


class Config:
    def __init__(self, mesh):
        self.mesh = mesh

    def load_payload(self):
        return {"bed_mesh": self.mesh}

    def get_axes(self):
        return [{"id": "x", "joint_numbers": [0]}, {"id": "y", "joint_numbers": [1]}, {"id": "z", "joint_numbers": [2]}]


class Stat:
    estop = False
    task_state = MachineState.ON.value
    task_mode = 3
    interp_state = 1
    homed = (1, 1, 1)
    probe_tripped = True
    probed_position = (0.0, 0.0, 0.0)

    def poll(self):
        pass


class Compensation:
    def __init__(self):
        self.on, self.history = True, []

    def is_enabled(self):
        return self.on

    def set_enabled(self, on):
        self.on = on
        self.history.append(on)
        return on


@pytest.fixture
def rig(monkeypatch, tmp_path):
    stat, lines, comp = Stat(), [], Compensation()
    where = {"x": 0.0, "y": 0.0}

    def dispatch(line, ack_timeout=1.0):
        lines.append(line)
        if m := re.search(r"X(-?[\d.]+) Y(-?[\d.]+)", line):
            where["x"], where["y"] = float(m.group(1)), float(m.group(2))
        if "G38.2" in line:
            stat.probed_position = (where["x"], where["y"], bed(where["x"], where["y"]))
        return None

    monkeypatch.setattr(probing, "dispatch_mdi", dispatch)
    monkeypatch.setattr(macro_module, "_IDLE_POLL_S", 0)
    monkeypatch.setattr(module, "read_hal_pin", lambda name: 0.0)
    monkeypatch.setattr(module, "get_bed_mesh_service", lambda: comp)
    monkeypatch.setattr(module.paths, "BED_MESHES_DIR", tmp_path / "bed_meshes")
    monkeypatch.setattr(module.paths, "ACTIVE_BED_MESH_FILE", tmp_path / "bed_mesh_active.txt")
    events = []
    levels = []

    class Console:
        def log_event(self, message, level=None, source=None):
            events.append(message)
            levels.append(str(getattr(level, "value", level)))

    monkeypatch.setattr(module, "get_console_logger", lambda: Console())
    return type("R", (), {"stat": stat, "lines": lines, "comp": comp, "tmp": tmp_path, "events": events, "levels": levels})


def test_probes_the_grid_zigzag_and_saves(rig):
    name = module.BedMeshProbeService(Config(MESH)).run(rig.stat, "pla")
    assert name == "pla"
    probes = [l for l in rig.lines if l.startswith("G53 G1")]
    assert probes == [
        "G53 G1 X10.0000 Y20.0000 F6000.0", "G53 G1 X60.0000 Y20.0000 F6000.0", "G53 G1 X110.0000 Y20.0000 F6000.0",
        "G53 G1 X110.0000 Y120.0000 F6000.0", "G53 G1 X60.0000 Y120.0000 F6000.0", "G53 G1 X10.0000 Y120.0000 F6000.0",
    ]
    # Relative (G53 takes only G0/G1): from machine Z3 down to 0.01 above Z-1.
    assert "G38.2 Z-3.9900 F120.0" in rig.lines
    assert not any(l.startswith("G53") and "G38" in l for l in rig.lines)
    saved = (rig.tmp / "bed_meshes" / "pla.txt").read_text().splitlines()
    assert saved[0] == "10 20 0.0500" and saved[5] == "110 120 0.3500"  # row by row, X fastest
    assert (rig.tmp / "bed_mesh_active.txt").read_text().splitlines()[0] == "# mesh: pla"
    assert rig.comp.history == [False, True]  # off while probing, on (reload) after


def test_zero_reference(rig):
    mesh = dict(MESH, zero_reference_position=[60, 70])
    module.BedMeshProbeService(Config(mesh)).run(rig.stat)
    saved = [float(l.split()[2]) for l in (rig.tmp / "bed_meshes" / "default.txt").read_text().splitlines()]
    assert abs(min(saved) - (bed(10, 20) - bed(60, 70))) < 1e-4


def test_failed_probe_restores_compensation(rig):
    rig.stat.probe_tripped = False
    with pytest.raises(module.BedMeshError, match="did not trigger"):
        module.BedMeshProbeService(Config(MESH)).run(rig.stat)
    assert rig.comp.on is True
    assert not (rig.tmp / "bed_meshes").exists()


def test_needs_homing_and_config(rig):
    rig.stat.homed = (1, 1, 0)
    with pytest.raises(BadRequestError, match="joint\\(s\\) 2"):
        module.BedMeshProbeService(Config(MESH)).run(rig.stat)
    with pytest.raises(BadRequestError, match="no \\[bed_mesh\\]"):
        module.BedMeshProbeService(Config(None)).run(rig.stat)


def test_command_parsing():
    assert module.parse_command("BED_MESH_CALIBRATE") == "default"
    assert module.parse_command("bed_mesh_calibrate PROFILE=pla ; comment") == "pla"
    assert module.parse_command("BED_MESH_CALIBRATEX") is None and module.parse_command("G29") is None
    with pytest.raises(BadRequestError):
        module.parse_command("BED_MESH_CALIBRATE PROFILE=../x")


def test_bilinear():
    xs, ys, z = [0.0, 10.0], [0.0, 10.0], [[0.0, 1.0], [2.0, 3.0]]
    assert module.bilinear(xs, ys, z, 5, 5) == 1.5 and module.bilinear(xs, ys, z, 99, -5) == 1.0


def test_leveling_runs_what_the_machine_has(monkeypatch):
    import services.LevelingService as leveling

    calls = []

    class Svc:
        def __init__(self, name, configured):
            self.name, self.configured = name, configured

        def settings(self):
            return {} if self.configured else None

        def run(self, stat, *a):
            calls.append(self.name)

    import services.ZTiltService as z
    monkeypatch.setattr(z, "get_z_tilt_service", lambda: Svc("z_tilt", True))
    monkeypatch.setattr(module, "get_bed_mesh_probe_service", lambda: Svc("mesh", True))
    monkeypatch.setattr(leveling, "get_console_logger", lambda: type("C", (), {"log_event": lambda *a, **k: None})())
    assert leveling.level(object()) is None and calls == ["z_tilt", "mesh"]
    monkeypatch.setattr(z, "get_z_tilt_service", lambda: Svc("z_tilt", False))
    calls.clear()
    assert leveling.level(object()) is None and calls == ["mesh"]


def test_points_logged_under_debug_the_result_under_info(rig):
    module.BedMeshProbeService(Config(MESH)).run(rig.stat, "pla")
    assert rig.levels[-1] == "INFO" and "saved and active" in rig.events[-1]
    assert set(rig.levels[:-1]) == {"DEBUG"}
    assert sum("-> Z" in e for e in rig.events) == 6  # one per probed point
    assert any(e.startswith("BED_MESH_CALIBRATE: row Y20:") for e in rig.events)
