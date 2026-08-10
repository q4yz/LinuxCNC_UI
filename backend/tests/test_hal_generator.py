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
    assert "loadrt [KINS]KINEMATICS" in rendered
    assert "loadrt [EMCMOT]EMCMOT" in rendered
    assert "loadrt remora-spi SPI_clk_div=64" in rendered
    assert "addf remora.read" in rendered
    assert "addf motion-command-handler" in rendered
    assert "addf motion-controller" in rendered
    assert "addf remora.update-freq" in rendered
    assert "addf remora.write" in rendered

    # Per-joint blocks (Remora mode uses INI section refs)
    assert "# joint 0 setup" in rendered
    assert "# joint 1 setup" in rendered
    assert "# joint 2 setup" in rendered
    assert "setp remora.joint.0.scale" in rendered
    assert "setp remora.joint.1.scale" in rendered
    assert "setp remora.joint.2.scale" in rendered

    # Signal wiring — Remora mode uses remora.joint channels, not
    # remora.stepgen.
    assert "net j0pos-cmd" in rendered
    assert "net j1pos-cmd" in rendered
    assert "net j2pos-cmd" in rendered
    assert "remora.joint.0.pos-cmd" in rendered

    # Tool-change loopback
    assert "net tool-prepare-loopback" in rendered
    assert "net tool-change-loopback" in rendered


def test_renderer_handles_missing_printer_velocity() -> None:
    """No ``[printer]`` block ⇒ default velocities still produce a valid HAL."""

    graph = _graph(steppers={"x": _stepper("x")})
    rendered = build_hal_from_graph(graph)

    assert "# joint 0 setup" in rendered
    assert "setp remora.joint.0.scale" in rendered


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
    rendered = HalGenerator().render(ini, graph)

    assert "# joint 0 setup" in rendered
    assert "# joint 1 setup" in rendered
    assert "remora.joint.0.pos-cmd" in rendered
    assert "remora.joint.1.pos-cmd" in rendered


def test_renderer_emits_endstop_wiring_for_stepgen_joints() -> None:
    """Each non-extruder joint gets a Remora input endstop line."""

    graph = _graph(
        steppers={
            "x": _stepper("x"),
            "y": _stepper("y"),
            "z": _stepper("z"),
        },
    )
    rendered = build_hal_from_graph(graph)

    # One endstop per X/Y/Z joint (extruder doesn't get one).
    assert "remora.input.00" in rendered
    assert "remora.input.01" in rendered
    assert "remora.input.02" in rendered
    # Symbolic signal names used.
    assert "x-stop" in rendered
    assert "y-stop" in rendered
    assert "z-stop" in rendered
    # Extruder has no endstop.
    assert "remora.input.03" not in rendered


def test_renderer_emits_pid_load_for_each_heater() -> None:
    """``loadrt PIDcontroller`` gets one alias per heater."""

    from modules.machineconfig.models import Heater

    graph = _graph(steppers={"x": _stepper("x")})
    graph.heaters["heater_bed"] = Heater(
        name="heater_bed",
        heater_pin="PA1",
        sensor_pin="PA3",
        sensor_type="NTC 100K",
        control="watermark",
    )
    graph.heaters["extruder"] = Heater(
        name="extruder",
        heater_pin="PA2",
        sensor_pin="PA4",
        sensor_type="PT1000",
        control="pid",
        pid_Kp=22.2,
        pid_Ki=1.08,
        pid_Kd=114,
    )

    rendered = build_hal_from_graph(graph)

    # Heaters are sorted alphabetically by canonical id, so ``extruder``
    # comes before ``heater_bed`` and produces ``PID-ext0`` before ``PID-bed``.
    assert "loadrt PIDcontroller names=PID-ext0,PID-bed" in rendered
    assert "addf PID-bed.compute" in rendered
    assert "addf PID-ext0.compute" in rendered
    # Per-heater PID config blocks (template uses aligned spaces).
    assert "setp PID-bed.KP" in rendered and "[BED]PID_KP" in rendered
    assert "setp PID-ext0.KP" in rendered and "[EXT0]PID_KP" in rendered


def test_renderer_emits_sp_pv_wiring() -> None:
    """Each PWM + Temperature module gets a symbolic SP/PV net line."""

    from modules.machineconfig.models import Extruder, Fan, Heater

    graph = _graph(steppers={"x": _stepper("x")})
    graph.heaters["heater_bed"] = Heater(
        name="heater_bed",
        heater_pin="PA1",
        sensor_pin="PA3",
        sensor_type="NTC 100K",
        control="watermark",
    )
    graph.heaters["extruder"] = Extruder(
        name="extruder",
        heater_pin="PA2",
        sensor_pin="PA4",
        sensor_type="PT1000",
        control="pid",
        pid_Kp=22.2,
        pid_Ki=1.08,
        pid_Kd=114,
    )
    graph.fans["fan_part_cooling"] = Fan(
        name="fan_part_cooling",
        pin="PA8",
        max_power=1.0,
    )

    rendered = build_hal_from_graph(graph)

    # SP wiring (bed, extruder, fan).
    assert "remora.SP.0" in rendered
    assert "remora.SP.1" in rendered
    assert "remora.SP.2" in rendered
    # PV wiring (bed, extruder).
    assert "remora.PV.0" in rendered
    assert "remora.PV.1" in rendered
    # Symbolic map comment block.
    assert "# Symbolic-to-positional Remora map" in rendered
    assert "remora.SP.0" in rendered
    assert "remora.SP.1" in rendered
    assert "remora.SP.2" in rendered



# --------------------------------------------------------------------- #
# Joint model basics                                                     #
# --------------------------------------------------------------------- #


def test_joint_section_name_format() -> None:
    j = Joint(joint_number=2, axis_letter="Z")
    assert j.section_name == "JOINT_2"


def test_axis_section_name_format() -> None:
    assert Axis(letter="Y").section_name == "AXIS_Y"