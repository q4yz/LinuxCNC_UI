"""``[homing_override]``: ``.cfg`` -> hardware.json + machine.ini
(`.agent/component/homing_override.md`)."""
from __future__ import annotations

import pytest

from core.homing_routine import HomingStep, homed_axes, parse_homing_routine
from MachineConfigParser import InvalidValueError, MachineConfigParser, MissingRequiredKeywordError
from services.machineconfig import AxisBuilder, AxisMappingPolicy
from services.machineconfig.hardware_json_generator import build_hardware_json
from services.machinetemplates.ini_template_generator import render_ini_template

CFG = """
[mcu]
connection: remora-spi

[stepper_x]
step_pin: PF13
dir_pin: PF12
endstop_pin: PG6
position_endstop: 0
position_max: 200

[stepper_y]
step_pin: PG0
dir_pin: PG1
endstop_pin: PG9
position_endstop: 0
position_max: 200

[stepper_z]
step_pin: PF11
dir_pin: PG3
endstop_pin: PG10
position_endstop: 0
position_max: 100

[estop]
{extra}
"""

ROUTINE = """
[homing_override]
gcode:
    G91
    G0 Z5    ; lift clear
    G90
    G28 X
    G28 Y
    G53 G0 X100 Y100
    G28 Z
"""


def _graph(extra=ROUTINE):
    return MachineConfigParser().parse_string(CFG.format(extra=extra))


def _payload(extra=ROUTINE):
    return build_hardware_json(_graph(extra), "m")


def test_reaches_hardware_json():
    assert _payload()["homing_override"] == {
        # configparser drops the inline "; lift clear" comment.
        "gcode": "G91\nG0 Z5\nG90\nG28 X\nG28 Y\nG53 G0 X100 Y100\nG28 Z",
        "axes": "xyz",
        "home_in_place": [],
    }


def test_absent_by_default():
    assert _payload("").get("homing_override") is None


def test_ini_allows_moves_before_homing():
    def ini(extra):
        graph = _graph(extra)
        axes = AxisBuilder(graph, policy=AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build()
        return render_ini_template("m", axes, homing_override=build_hardware_json(graph, "m").get("homing_override") is not None)

    assert "NO_FORCE_HOMING = 1" in ini(ROUTINE)
    assert "NO_FORCE_HOMING" not in ini("")


def test_axes_subset():
    extra = "[homing_override]\naxes: z\ngcode:\n    G0 X100 Y100\n    G28 Z\n"
    assert _payload(extra)["homing_override"]["axes"] == "z"


def test_bare_g28_homes_everything():
    assert _payload("[homing_override]\ngcode:\n    G91\n    G0 Z5\n    G90\n    G28\n")["homing_override"]


@pytest.mark.parametrize(
    ("extra", "error"),
    [
        ("[homing_override]\naxes: xyz\n", MissingRequiredKeywordError),
        (ROUTINE.replace("    G28 Z\n", ""), InvalidValueError),              # z never homed
        (ROUTINE.replace("G28 Y", "G28 Y G0 X1"), InvalidValueError),         # G28 with other words
        (ROUTINE.replace("G28 Z", "G28 B"), InvalidValueError),               # no axis B
        (ROUTINE.replace("gcode:", "axes: xq\ngcode:"), InvalidValueError),   # not an axis letter
        (ROUTINE.replace("gcode:", "axes: xb\ngcode:"), InvalidValueError),   # no axis B
    ],
)
def test_errors(extra, error):
    with pytest.raises(error):
        _payload(extra)


def test_routine_parser():
    steps = parse_homing_routine("G91\n(comment only)\nG0 Z5 (lift)\nN10 g28 x0 y\nG28.1\n#<z> = 5\nG28")
    assert steps == [
        HomingStep("mdi", "G91"),
        HomingStep("mdi", "G0 Z5 (lift)"),
        HomingStep("home", "N10 g28 x0 y", ("X", "Y")),
        HomingStep("mdi", "G28.1"),  # LinuxCNC's own "store position", not a home
        HomingStep("mdi", "#<z> = 5"),
        HomingStep("home", "G28", ()),
    ]
    assert homed_axes(steps) is None
    assert homed_axes(parse_homing_routine("G28 X\nG28 Z")) == {"X", "Z"}


EXTRUDER = """
[extruder]
step_pin: PE2
dir_pin: PE3
microsteps: 16
rotation_distance: 33.5
heater_pin: PA2
sensor_type: Generic 3950
sensor_pin: PF4
control: watermark
min_temp: 0
max_temp: 250
"""


def test_extruder_is_homed_in_place_without_g28_a():
    override = _payload(EXTRUDER + ROUTINE)["homing_override"]
    # The user's routine homes X/Y/Z only; the extruder's "a" is left to
    # the runner, and is not part of the default `axes`.
    assert override["axes"] == "xyz"
    assert override["home_in_place"] == ["a"]


def test_extruder_homed_by_the_routine_is_not_repeated():
    routine = ROUTINE + "    G28 A\n"
    assert _payload(EXTRUDER + routine)["homing_override"]["home_in_place"] == []


def test_bare_g28_leaves_nothing_to_home_in_place():
    extra = EXTRUDER + "[homing_override]\ngcode:\n    G28\n"
    assert _payload(extra)["homing_override"]["home_in_place"] == []


def test_z_tilt_adjust_is_a_routine_step():
    steps = parse_homing_routine("G28\nz_tilt_adjust\nG28 Z")
    assert [s.kind for s in steps] == ["home", "z_tilt", "home"]
