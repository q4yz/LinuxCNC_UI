"""The mock takes its machine from hardware.json and keeps HAL values."""
from __future__ import annotations

import math

import pytest

from hardware.mock.LinuxCNCMock import LinuxCNCMock
from hardware.mock.config import MockMachineConfig

PRINTER = {
    "max_velocity": 300.0,
    "axes": [
        {"id": "x", "joint_numbers": [0], "position_max": 200.0, "position_endstop": 0.0, "max_velocity": 300.0},
        {"id": "y", "joint_numbers": [1], "position_max": 180.0, "position_endstop": 180.0, "max_velocity": 300.0},
        {"id": "z", "joint_numbers": [2], "position_min": -2.0, "position_max": 250.0, "max_velocity": 5.0},
    ],
    "joints": [{"joint_number": n} for n in range(4)],  # joint 3: the extruder
    "tools": [
        {"id": "heater_extruder", "type": "extruder", "sensor": "extruder", "max_temp": 250.0},
        {"id": "heater_bed", "type": "heated_bed", "sensor": "bed", "max_temp": 110.0},
    ],
    "temperature_sensors": [
        {"id": "extruder", "pin": "PF4"},
        {"id": "bed", "pin": "PF3"},
        {"id": "chamber", "pin": "PF5"},
    ],
}


@pytest.fixture
def mock() -> LinuxCNCMock:
    m = LinuxCNCMock()
    m.register_hardware(PRINTER)
    return m


def run(mock: LinuxCNCMock, seconds: float) -> None:
    for _ in range(round(seconds / 0.1)):
        mock.tick(0.1)


def test_config_from_payload():
    config = MockMachineConfig.from_payload(PRINTER)
    assert [a.letter for a in config.axes] == ["x", "y", "z"]
    assert config.joint_count == 4
    assert config.axis_mask == 0b111
    x, y, z = config.axes
    assert (x.min_limit, x.max_limit) == (0.0, 200.0)  # no position_min: from 0
    assert (z.min_limit, z.max_limit, z.max_velocity) == (-2.0, 250.0, 5.0)
    assert y.home == 180.0
    assert config.heaters["heater_bed"].max_temp == 110.0


def test_empty_payload_is_an_unlimited_xyz():
    config = MockMachineConfig.from_payload({})
    assert [a.letter for a in config.axes] == ["x", "y", "z"]
    assert config.axes[0].max_limit == math.inf


def test_a_four_axis_machine():
    config = MockMachineConfig.from_payload({"axes": [{"id": l, "joint_numbers": [i]} for i, l in enumerate("xyza")]})
    m = LinuxCNCMock()
    m.register_hardware({"axes": [{"id": l, "joint_numbers": [i]} for i, l in enumerate("xyza")]})
    assert config.axis_mask == 0b1111
    assert sorted(m.internal_state.axes) == [0, 1, 2, 3]
    assert m.internal_state.homed == [0, 0, 0, 0]


def test_stat_follows_the_config(mock):
    stat = mock.linuxcnc.stat()
    assert stat.joints == 4 and len(stat.homed) == 4
    assert stat.axis_mask == 0b111
    assert stat.max_velocity == 300.0


def test_jog_stops_at_the_soft_limit(mock):
    cmd = mock.linuxcnc.command()
    cmd.jog(mock.linuxcnc.JOG_CONTINUOUS, False, 0, 300.0)
    run(mock, 2.0)
    assert mock.linuxcnc.stat().actual_position[0] == 200.0
    cmd.jog(mock.linuxcnc.JOG_CONTINUOUS, False, 0, -300.0)
    run(mock, 2.0)
    assert mock.linuxcnc.stat().actual_position[0] == 0.0


def test_jog_speed_is_capped_by_the_axis(mock):
    cmd = mock.linuxcnc.command()
    cmd.jog(mock.linuxcnc.JOG_INCREMENT, False, 2, 100.0, 10.0)  # Z max 5 mm/s
    run(mock, 1.0)
    assert mock.linuxcnc.stat().actual_position[2] == pytest.approx(5.0)


def test_joint_jog_moves_the_joints_axis(mock):
    mock.linuxcnc.command().jog(mock.linuxcnc.JOG_INCREMENT, True, 1, 50.0, 20.0)
    run(mock, 1.0)
    assert mock.linuxcnc.stat().actual_position[1] == pytest.approx(20.0)


def test_homing_goes_to_the_endstop_position(mock):
    mock.linuxcnc.command().home(-1)
    stat = mock.linuxcnc.stat()
    assert stat.homed == [1, 1, 1, 1]
    assert stat.actual_position[1] == 180.0


def test_mdi_moves(mock):
    cmd = mock.linuxcnc.command()
    cmd.mdi("G90 G0 X50 Y20")
    run(mock, 1.0)
    assert mock.linuxcnc.stat().actual_position[:2] == (50.0, 20.0)
    cmd.mdi("G91 G1 X-10 F600")  # 10 mm/s
    run(mock, 0.5)
    assert mock.linuxcnc.stat().actual_position[0] == pytest.approx(45.0)
    run(mock, 1.0)
    assert mock.linuxcnc.stat().actual_position[0] == pytest.approx(40.0)
    cmd.mdi("G90 G0 X999")  # clamped to the travel
    run(mock, 2.0)
    assert mock.linuxcnc.stat().actual_position[0] == 200.0


def test_estop_stops_motion(mock):
    mock.linuxcnc.command().mdi("G0 X100")
    run(mock, 0.1)
    mock.internal_state.trigger_estop()
    position = mock.linuxcnc.stat().actual_position[0]
    run(mock, 1.0)
    assert mock.linuxcnc.stat().actual_position[0] == position


def test_a_program_runs_through_its_lines(mock, tmp_path):
    program = tmp_path / "part.ngc"
    program.write_text("".join(f"G1 X{i}\n" for i in range(150)))
    cmd = mock.linuxcnc.command()
    cmd.program_open(str(program))
    stat = mock.linuxcnc.stat()
    assert stat.total_lines == 150
    cmd.auto(mock.linuxcnc.AUTO_RUN, 0)
    run(mock, 1.0)
    assert stat.interp_state == mock.linuxcnc.INTERP_READING and stat.current_line == 100
    cmd.auto(mock.linuxcnc.AUTO_PAUSE)
    run(mock, 1.0)
    assert stat.current_line == 100 and stat.interp_state == mock.linuxcnc.INTERP_PAUSED
    cmd.auto(mock.linuxcnc.AUTO_RESUME)
    run(mock, 1.0)
    assert stat.interp_state == mock.linuxcnc.INTERP_IDLE and stat.current_line == 150


def test_heater_is_capped_and_off_in_estop(mock):
    hal = mock.hal
    hal.set_p("webgui.target-temperature_bed", 200.0)
    run(mock, 5.0)
    assert hal.get_value("webgui.bed") == 25.0  # E-stop: heat-ok low
    mock.internal_state.reset_estop()
    run(mock, 60.0)
    assert hal.get_value("webgui.bed") == pytest.approx(110.0)  # max_temp


def test_a_free_sensor_reads_room_temperature(mock):
    assert mock.hal.get_value("webgui.chamber") == 25.0


def test_unowned_pins_keep_their_value(mock):
    mock.hal.set_p("webgui.fan_part", 0.6)
    mock.linuxcnc.command().setp("webgui.led_strip-red", 1.0)
    assert mock.hal.get_value("webgui.fan_part") == 0.6
    assert mock.hal.get_value("webgui.led_strip-red") == 1.0
    assert mock.hal.get_value("webgui.never-written") == 0.0
    assert mock.hal.pins["webgui.fan_part"] == 0.6


def test_reregistering_replaces_the_machine(mock):
    mock.register_hardware({"axes": [{"id": "x", "joint_numbers": [0]}], "tools": []})
    ids = {getattr(c, "id", None) for c in mock.internal_hal.components}
    assert ids == {"estop", "debug-signals"}
    assert sorted(mock.internal_state.axes) == [0]
    assert mock.hal.get_value("webgui.estop") == 1  # always-on still answers
