"""Bed mesh end to end: ``[bed_mesh]`` -> ``hardware.json`` -> the
``compensation`` component in machine.hal / webgui_connections.hal, and
the saved meshes (`.agent/component/bed_mesh.md`)."""
from __future__ import annotations

import json

import pytest

from exceptions import BadRequestError, ConflictError
from MachineConfigParser import InvalidValueError, MachineConfigParser
from models.BedMeshModels import BedMeshDefaults, BedMeshGrid
from services.BedMeshService import BedMeshService
from services.halcompiler import compile_machine_hal, render_webgui_connections
from services.machineconfig.hardware_json_generator import build_hardware_json

CFG = """
[mcu]
connection: remora-spi

[stepper_x]
step_pin: PF13
dir_pin: PF12
position_endstop: 0
position_max: 220

[stepper_y]
step_pin: PG0
dir_pin: PG1
position_endstop: 0
position_max: 180

[estop]
{bed_mesh}
"""


def _payload(tmp_path, bed_mesh="[bed_mesh]\nprobe_count: 3, 3\n"):
    cfg = tmp_path / "machine.cfg"
    cfg.write_text(CFG.format(bed_mesh=bed_mesh), encoding="utf-8")
    return json.loads(json.dumps(build_hardware_json(MachineConfigParser().parse(cfg), "m")))


# -- config ----------------------------------------------------------------- #


@pytest.mark.parametrize("raw, expected", [("3, 3", [3, 3]), ("5,4", [5, 4]), ("4", [4, 4])])
def test_probe_count_reaches_hardware_json(tmp_path, raw, expected):
    assert _payload(tmp_path, f"[bed_mesh]\nprobe_count: {raw}\n")["bed_mesh"]["probe_count"] == expected


def test_probe_count_defaults_to_3_by_3(tmp_path):
    assert _payload(tmp_path, "[bed_mesh]\n")["bed_mesh"]["probe_count"] == [3, 3]


@pytest.mark.parametrize("raw", ["2, 3", "3, x", "3, 3, 3"])
def test_bad_probe_counts_are_rejected(tmp_path, raw):
    with pytest.raises(InvalidValueError, match="probe_count"):
        _payload(tmp_path, f"[bed_mesh]\nprobe_count: {raw}\n")


# -- HAL --------------------------------------------------------------------- #


def test_a_bed_mesh_loads_the_compensation_component_and_sums_the_z_offset(tmp_path):
    text = compile_machine_hal(_payload(tmp_path))
    assert "loadusr -Wn compensation python3 /usr/local/bin/remora-compensation" in text
    assert "bed_mesh_active.txt cubic" in text
    assert "net bed-mesh-counts compensation.counts => bed-mesh-float.in" in text
    assert "setp z-eoffset-sum.gain0 1000" in text
    assert "net z-eoffset-counts z-eoffset-counts.out => axis.z.eoffset-counts" in text


def test_the_pause_lift_joins_the_sum_instead_of_driving_eoffset_counts(tmp_path):
    lines = render_webgui_connections(_payload(tmp_path))
    assert "net bed-mesh-enable webgui.bed-mesh-enable => compensation.enable-in" in lines
    assert "net bed-mesh-x halui.axis.x.pos-relative => compensation.x-pos" in lines
    assert "net inspect-z-lift-bit webgui.inspect-z-lift => z-lift-float.in" in lines
    assert "setp axis.z.eoffset-scale 0.001" in lines
    # One writer on axis.z.eoffset-counts: machine.hal's sum, not the lift.
    assert "axis.z.eoffset-counts" not in lines


def test_without_a_bed_mesh_nothing_changes(tmp_path):
    payload = _payload(tmp_path, "")
    assert "compensation" not in compile_machine_hal(payload)
    lines = render_webgui_connections(payload)
    assert "net inspect-z-lift-s32 inspect-z-lift-conv.out => axis.z.eoffset-counts" in lines
    assert "compensation" not in lines


# -- saved meshes ------------------------------------------------------------ #


@pytest.fixture()
def service(tmp_path):
    return BedMeshService(tmp_path / "bed_meshes", tmp_path / "bed_mesh_active.txt")


def test_a_new_mesh_is_flat_over_the_requested_grid(service):
    grid = service.create("first", BedMeshDefaults(x_min=0, x_max=200, y_min=10, y_max=110, x_count=3, y_count=2))
    assert (grid.xs, grid.ys, grid.z) == ([0, 100, 200], [10, 110], [[0.0] * 3, [0.0] * 3])
    assert service.read("first") == grid
    assert service.list().names == ["first"]


def test_saved_meshes_use_the_gridprobe_format(service, tmp_path):
    service.save(BedMeshGrid(name="m", xs=[0, 10], ys=[0, 20], z=[[0.1, 0.2], [0.3, -0.4]]))
    assert (tmp_path / "bed_meshes" / "m.txt").read_text(encoding="utf-8").splitlines() == [
        "0 0 0.1000", "10 0 0.2000", "0 20 0.3000", "10 20 -0.4000",
    ]


def test_activating_copies_the_mesh_for_the_component(service, tmp_path):
    service.save(BedMeshGrid(name="m", xs=[0, 10], ys=[0, 20], z=[[0.1, 0.2], [0.3, 0.4]]))
    assert service.activate("m").active == "m"
    lines = (tmp_path / "bed_mesh_active.txt").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# mesh: m" and lines[1] == "0 0 0.1000"
    # Saving the active mesh refreshes the component's copy.
    service.save(BedMeshGrid(name="m", xs=[0, 10], ys=[0, 20], z=[[0.5, 0.2], [0.3, 0.4]]))
    assert "0 0 0.5000" in (tmp_path / "bed_mesh_active.txt").read_text(encoding="utf-8")


def test_the_active_mesh_cannot_be_deleted(service):
    service.create("a", BedMeshDefaults())
    service.create("b", BedMeshDefaults())
    service.activate("a")
    with pytest.raises(ConflictError):
        service.delete("a")
    service.delete("b")
    assert service.list().names == ["a"]


def test_a_ragged_or_unsorted_grid_and_bad_names_are_rejected(service):
    with pytest.raises(BadRequestError):
        service.save(BedMeshGrid(name="m", xs=[0, 10], ys=[0, 20], z=[[0.1], [0.3, 0.4]]))
    with pytest.raises(BadRequestError):
        service.save(BedMeshGrid(name="m", xs=[10, 0], ys=[0, 20], z=[[0, 0], [0, 0]]))
    with pytest.raises(BadRequestError):
        service.read("../etc/passwd")


def test_defaults_come_from_probe_count_and_the_xy_limits(tmp_path):
    defaults = BedMeshService.defaults_for(_payload(tmp_path, "[bed_mesh]\nprobe_count: 5, 4\n"))
    assert (defaults.x_count, defaults.y_count, defaults.x_max, defaults.y_max) == (5, 4, 220.0, 180.0)


def test_a_bed_mesh_machine_starts_with_a_flat_active_mesh(service, tmp_path):
    service.ensure_active(_payload(tmp_path))
    listing = service.list()
    assert (listing.names, listing.active) == (["flat"], "flat")
    assert len(service.read("flat").xs) == 3


def test_probing_settings_reach_hardware_json(tmp_path):
    mesh = _payload(tmp_path, "[bed_mesh]\nprobe_count: 5, 4\nmesh_min: 10, 15\nmesh_max: 190, 185\n"
                              "speed: 120\nhorizontal_move_z: 3\nprobe_speed: 2\nzero_reference_position: 100, 100\n")["bed_mesh"]
    assert mesh["mesh_min"] == [10.0, 15.0] and mesh["mesh_max"] == [190.0, 185.0]
    assert (mesh["speed"], mesh["horizontal_move_z"], mesh["probe_speed"]) == (120.0, 3.0, 2.0)
    assert mesh["zero_reference_position"] == [100.0, 100.0]


def test_probed_area_defaults_to_the_travel(tmp_path):
    mesh = _payload(tmp_path, "[bed_mesh]\n")["bed_mesh"]
    assert mesh["mesh_min"][0] <= mesh["mesh_max"][0] and mesh.get("zero_reference_position") is None


@pytest.mark.parametrize("extra", ["mesh_min: 10\n", "mesh_min: 50, 50\nmesh_max: 40, 90\n", "speed: 0\n", "horizontal_move_z: -1\n"])
def test_bad_probing_settings(tmp_path, extra):
    with pytest.raises(InvalidValueError):
        _payload(tmp_path, "[bed_mesh]\n" + extra)
