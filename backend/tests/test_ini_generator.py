"""Tests for the AxisBuilder / IniGenerator pipeline."""

from __future__ import annotations

from modules.machineconfig.compilers.axis_builder import (
    AxisBuilder,
    AxisMappingPolicy,
    stepgen_scale,
)
from modules.machineconfig.compilers.ini_generator import (
    IniGenerator,
    TemplateError,
    build_ini_from_graph,
    render_string,
)
from modules.machineconfig.models import (
    Axis,
    IniConfig,
    Joint,
    MachineConfigGraph,
    Printer,
    Stepper,
)


# --------------------------------------------------------------------- #
# Fixtures / helpers                                                     #
# --------------------------------------------------------------------- #


def _graph(
    printer: Printer | None = None,
    steppers: dict[str, Stepper] | None = None,
) -> MachineConfigGraph:
    return MachineConfigGraph(
        printer=printer,
        steppers=steppers or {},
    )


def _stepper(
    axis: str = "x",
    microsteps: int | None = 16,
    rotation_distance: float | None = 40.0,
    position_max: float | None = 300.0,
    position_endstop: float | None = 0.0,
    **extra,
) -> Stepper:
    return Stepper(
        axis=axis,
        microsteps=microsteps,
        rotation_distance=rotation_distance,
        position_max=position_max,
        position_endstop=position_endstop,
        **extra,
    )


# --------------------------------------------------------------------- #
# Scale formula                                                          #
# --------------------------------------------------------------------- #


def test_stepgen_scale_uses_microsteps_and_full_steps() -> None:
    """SCALE = microsteps * 200 / rotation_distance."""

    s = _stepper(microsteps=16, rotation_distance=40.0)
    assert stepgen_scale(s) == 80.0  # 16 * 200 / 40


def test_stepgen_scale_zero_when_rotation_distance_missing() -> None:
    assert stepgen_scale(_stepper(rotation_distance=None)) == 0.0
    assert stepgen_scale(_stepper(rotation_distance=0)) == 0.0
    assert stepgen_scale(_stepper(microsteps=None)) == 0.0


# --------------------------------------------------------------------- #
# AxisBuilder                                                            #
# --------------------------------------------------------------------- #


def test_builder_emits_one_axis_per_letter() -> None:
    graph = _graph(
        printer=Printer(max_velocity=250.0, max_accel=750.0),
        steppers={
            "x": _stepper("x"),
            "y": _stepper("y"),
            "z": _stepper("z", rotation_distance=8.0, position_max=280.0),
        },
    )
    axes = AxisBuilder(graph).build()

    assert [a.letter for a in axes] == ["X", "Y", "Z"]
    assert all(len(a.joints) == 1 for a in axes)
    assert axes[2].offset_av_ratio == 0.2  # Z-specific


def test_builder_merges_dual_motor_axis_into_one_axis() -> None:
    """``stepper_y`` + ``stepper_y1`` ⇒ one Y axis, one joint (merge)."""

    graph = _graph(
        steppers={
            "y": _stepper("y"),
            "y1": _stepper("y", microsteps=32, rotation_distance=40.0),
        },
    )
    axes = AxisBuilder(graph, AxisMappingPolicy.MERGE_INTO_SINGLE_JOINT).build()

    assert [a.letter for a in axes] == ["Y"]
    assert len(axes[0].joints) == 1


def test_builder_splits_dual_motor_axis_into_multiple_joints() -> None:
    """Split policy keeps each stepper as its own joint under the axis."""

    graph = _graph(
        steppers={
            "y": _stepper("y"),
            "y1": _stepper("y"),
        },
    )
    axes = AxisBuilder(graph, AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build()

    assert [a.letter for a in axes] == ["Y"]
    assert len(axes[0].joints) == 2
    assert axes[0].joints[0].joint_number == 0
    assert axes[0].joints[1].joint_number == 1


def test_builder_honours_canonical_axis_order() -> None:
    """Axes come out in X, Y, Z order regardless of insertion order."""

    graph = _graph(
        steppers={
            "z": _stepper("z"),
            "x": _stepper("x"),
            "y": _stepper("y"),
        },
    )
    assert [a.letter for a in AxisBuilder(graph).build()] == ["X", "Y", "Z"]


def test_builder_uses_printer_velocity_when_stepper_missing() -> None:
    graph = _graph(
        printer=Printer(max_velocity=300.0, max_accel=3000.0),
        steppers={"x": _stepper("x")},
    )
    axes = AxisBuilder(graph).build()
    assert axes[0].max_velocity == 300.0
    assert axes[0].joints[0].max_velocity == 300.0


def test_builder_position_min_default_zero_when_missing() -> None:
    """Klipper schema doesn't accept position_min as a stepper keyword today."""

    graph = _graph(steppers={"x": _stepper("x")})
    axis = AxisBuilder(graph).build()[0]
    assert axis.min_limit == 0.0  # safe default; not a validation failure


# --------------------------------------------------------------------- #
# Template substitution                                                  #
# --------------------------------------------------------------------- #


def test_render_string_substitutes_nested_keys() -> None:
    assert render_string("a {x.y}", {"x": {"y": 7}}) == "a 7"


def test_render_string_supports_mini_format() -> None:
    assert render_string("{v:.2f}", {"v": 1.5}) == "1.50"
    assert render_string("{v:d}", {"v": 5}) == "5"


def test_render_string_raises_template_error_on_missing_key() -> None:
    import pytest

    with pytest.raises(TemplateError):
        render_string("{missing}", {})


# --------------------------------------------------------------------- #
# IniGenerator end-to-end                                                #
# --------------------------------------------------------------------- #


def test_renderer_emits_full_template_for_xy_profile() -> None:
    graph = _graph(
        printer=Printer(max_velocity=250.0, max_accel=750.0),
        steppers={
            "x": _stepper("x"),
            "y": _stepper("y"),
            "z": _stepper(
                "z", rotation_distance=8.0, position_max=280.0
            ),
        },
    )
    ini = build_ini_from_graph(graph)
    rendered = IniGenerator().render(ini)

    # Static header keys
    assert "[EMC]" in rendered
    assert "MACHINE = Remora-XY" in rendered
    assert "VERSION = 1.1" in rendered
    assert "[KINS]" in rendered
    assert "JOINTS = 3" in rendered
    assert "KINEMATICS = trivkins coordinates=X Y Z" in rendered
    assert "[TRAJ]" in rendered
    assert "MAX_LINEAR_VELOCITY = 250" in rendered

    # Per-axis blocks, one per axis
    assert "[AXIS_X]" in rendered
    assert "[AXIS_Y]" in rendered
    assert "[AXIS_Z]" in rendered

    # Per-joint blocks
    assert "[JOINT_0]" in rendered
    assert "[JOINT_1]" in rendered
    assert "[JOINT_2]" in rendered

    # Klipper→LinuxCNC field mapping
    assert "MAX_LIMIT = 300" in rendered  # position_max
    assert "HOME_OFFSET = 0" in rendered  # position_endstop
    assert "MIN_LIMIT = 0" in rendered  # position_min default
    assert "SCALE = 80" in rendered  # 16 * 200 / 40
    assert "SCALE = 400" in rendered  # Z: 16 * 200 / 8

    # Z-specific extras
    assert "OFFSET_AV_RATIO = 0.2" in rendered

    # Footer
    assert "[EMCIO]" in rendered
    assert "TOOL_TABLE = tool.tbl" in rendered


def test_renderer_handles_missing_printer_velocity() -> None:
    """No ``[printer]`` block ⇒ default velocities still produce a valid INI."""

    graph = _graph(steppers={"x": _stepper("x")})
    ini = build_ini_from_graph(graph)
    rendered = IniGenerator().render(ini)

    assert "MAX_LINEAR_VELOCITY = 250" in rendered  # default
    assert "[AXIS_X]" in rendered


def test_renderer_handles_extra_motor_with_split_policy() -> None:
    """Split policy: secondary joints are surfaced as commented hints.

    The renderer emits one canonical ``[JOINT_N]`` block per axis and
    surfaces the rest as ``# extra joint N: scale=...`` lines so the
    HAL renderer can promote them later. This keeps the diff against
    the legacy single-motor INI readable while still exposing the
    multi-motor information.
    """

    graph = _graph(
        printer=Printer(max_velocity=250.0, max_accel=750.0),
        steppers={
            "y": _stepper("y"),
            "y1": _stepper("y"),
        },
    )
    # Re-build with split policy:
    from modules.machineconfig.compilers.axis_builder import AxisBuilder

    ini = IniConfig(
        printer=graph,
        axes=AxisBuilder(graph, AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build(),
    )
    rendered = IniGenerator().render(ini)

    assert "[AXIS_Y]" in rendered
    assert "[JOINT_0]" in rendered
    # Secondary joint is surfaced as a comment line, not a full block.
    assert "# NOTE: 2 steppers mapped to this axis" in rendered
    assert "# extra joint 1: scale=80" in rendered


def test_renderer_rejects_axis_without_joints() -> None:
    """Defensive: an axis with no joints is a programmer error."""

    from modules.machineconfig.models import Axis, IniConfig

    broken = IniConfig(
        printer=None,
        axes=[Axis(letter="X", joints=[])],
        joints_count=0,
        coordinates="X",
    )
    import pytest

    with pytest.raises(TemplateError):
        IniGenerator().render(broken)


# --------------------------------------------------------------------- #
# Joint model basics                                                     #
# --------------------------------------------------------------------- #


def test_joint_section_name_format() -> None:
    j = Joint(joint_number=2, axis_letter="Z")
    assert j.section_name == "JOINT_2"


def test_axis_section_name_format() -> None:
    assert Axis(letter="Y").section_name == "AXIS_Y"