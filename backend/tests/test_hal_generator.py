"""Tests for the HalGenerator pipeline."""

from __future__ import annotations

from modules.machineconfig.compilers.hal_generator import (
    HalGenerator,
    build_hal_from_graph,
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
# HalGenerator end-to-end                                                #
# --------------------------------------------------------------------- #


def test_renderer_emits_full_template_for_xyz_profile() -> None:
    graph = _graph(
        printer=Printer(max_velocity=250.0, max_accel=750.0),
        steppers={
            "x": _stepper("x"),
            "y": _stepper("y"),
            "z": _stepper("z", rotation_distance=8.0, position_max=280.0),
        },
    )
    rendered = build_hal_from_graph(graph)

    # Static header keys
    assert "loadrt remora-xyz chip_type=STM32F429" in rendered
    assert "loadrt thread names=base-thread,servo-thread" in rendered
    assert "addf remora.read" in rendered
    assert "addf motion-command-handler" in rendered
    assert "addf motion-controller" in rendered
    assert "addf remora.update-freq" in rendered
    assert "addf remora.write" in rendered

    # Per-joint blocks
    assert "# --- X axis (Joint 0) ---" in rendered
    assert "# --- Y axis (Joint 1) ---" in rendered
    assert "# --- Z axis (Joint 2) ---" in rendered

    # Signal wiring
    assert "net xpos-cmd  joint.0.motor-pos-cmd  => remora.stepgen.00.position-cmd" in rendered
    assert "net ypos-cmd  joint.1.motor-pos-cmd  => remora.stepgen.01.position-cmd" in rendered
    assert "net zpos-cmd  joint.2.motor-pos-cmd  => remora.stepgen.02.position-cmd" in rendered

    # Scale values
    assert "setp remora.stepgen.00.position-scale 80" in rendered
    assert "setp remora.stepgen.01.position-scale 80" in rendered
    assert "setp remora.stepgen.02.position-scale 400" in rendered

    # Enable signals
    assert "net machine-is-on => remora.stepgen.00.enable remora.stepgen.01.enable remora.stepgen.02.enable" in rendered


def test_renderer_handles_missing_printer_velocity() -> None:
    """No ``[printer]`` block ⇒ default velocities still produce a valid HAL."""

    graph = _graph(steppers={"x": _stepper("x")})
    rendered = build_hal_from_graph(graph)

    assert "# --- X axis (Joint 0) ---" in rendered
    assert "setp remora.stepgen.00.position-scale 80" in rendered


def test_renderer_handles_extra_motor_with_split_policy() -> None:
    """Split policy emits both joint blocks under a shared axis."""

    from modules.machineconfig.compilers.axis_builder import (
        AxisBuilder,
        AxisMappingPolicy,
    )

    graph = _graph(
        printer=Printer(max_velocity=250.0, max_accel=750.0),
        steppers={
            "y": _stepper("y"),
            "y1": _stepper("y"),
        },
    )
    ini = IniConfig(
        printer=graph,
        axes=AxisBuilder(graph, AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build(),
    )
    rendered = HalGenerator().render(ini)

    assert "# --- Y axis (Joint 0) ---" in rendered
    assert "# --- Y axis (Joint 1) ---" in rendered
    assert "net ypos-cmd  joint.0.motor-pos-cmd  => remora.stepgen.00.position-cmd" in rendered
    assert "net ypos-cmd  joint.1.motor-pos-cmd  => remora.stepgen.01.position-cmd" in rendered


def test_renderer_includes_pin_comments() -> None:
    """Pin assignments are included as comments for documentation."""

    graph = _graph(
        steppers={
            "x": _stepper("x", step_pin="PF13", dir_pin="PF12", enable_pin="!PF14"),
        },
    )
    rendered = build_hal_from_graph(graph)

    assert "# Pins: step=PF13, dir=PF12, enable=!PF14" in rendered


def test_renderer_handles_missing_pins() -> None:
    """Missing pins render as N/A without crashing."""

    graph = _graph(steppers={"x": _stepper("x")})
    rendered = build_hal_from_graph(graph)

    assert "# Pins: step=N/A, dir=N/A, enable=N/A" in rendered


# --------------------------------------------------------------------- #
# Joint model basics                                                     #
# --------------------------------------------------------------------- #


def test_joint_section_name_format() -> None:
    j = Joint(joint_number=2, axis_letter="Z")
    assert j.section_name == "JOINT_2"


def test_axis_section_name_format() -> None:
    assert Axis(letter="Y").section_name == "AXIS_Y"