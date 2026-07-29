"""Tests for the hal_type feature (remora vs parallel HAL output)."""

from __future__ import annotations

from modules.machineconfig.compilers.hal_generator import (
    HalGenerator,
    build_hal_from_graph,
)
from modules.machineconfig.models import (
    IniConfig,
    MachineConfigGraph,
    MCU,
    Printer,
    Stepper,
)


# --------------------------------------------------------------------- #
# Fixtures / helpers                                                     #
# --------------------------------------------------------------------- #


def _graph(
    printer: Printer | None = None,
    steppers: dict[str, Stepper] | None = None,
    mcu: MCU | None = None,
) -> MachineConfigGraph:
    return MachineConfigGraph(
        printer=printer,
        steppers=steppers or {},
        mcu=mcu,
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
# hal_type selection                                                     #
# --------------------------------------------------------------------- #


def test_hal_type_defaults_to_remora() -> None:
    graph = _graph(steppers={"x": _stepper("x")})
    rendered = build_hal_from_graph(graph)

    assert "remora.stepgen.00" in rendered
    # "stepgen.0" appears inside "remora.stepgen.00" — check for the
    # parallel-specific timing params instead.
    assert "steplen" not in rendered


def test_hal_type_remora_explicit() -> None:
    graph = _graph(
        steppers={"x": _stepper("x")},
        mcu=MCU(hal_type="remora"),
    )
    rendered = build_hal_from_graph(graph)

    assert "remora.stepgen.00" in rendered
    assert "steplen" not in rendered


def test_hal_type_parallel() -> None:
    graph = _graph(
        steppers={"x": _stepper("x")},
        mcu=MCU(hal_type="parallel"),
    )
    rendered = build_hal_from_graph(graph)

    assert "stepgen.0" in rendered
    assert "remora.stepgen" not in rendered
    assert "steplen" in rendered
    assert "stepspace" in rendered
    assert "dirhold" in rendered
    assert "dirsetup" in rendered
    assert "maxaccel" in rendered


def test_hal_type_parallel_enable_signals() -> None:
    graph = _graph(
        steppers={"x": _stepper("x"), "y": _stepper("y")},
        mcu=MCU(hal_type="parallel"),
    )
    rendered = build_hal_from_graph(graph)

    assert "net machine-is-on => stepgen.0.enable stepgen.1.enable" in rendered


def test_hal_type_invalid_raises() -> None:
    graph = _graph(steppers={"x": _stepper("x")})
    try:
        build_hal_from_graph(graph, hal_type="invalid")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "Unsupported hal_type" in str(e)


# --------------------------------------------------------------------- #
# HalGenerator class                                                     #
# --------------------------------------------------------------------- #


def test_hal_generator_remora_template() -> None:
    graph = _graph(steppers={"x": _stepper("x")})
    from modules.machineconfig.compilers.ini_generator import build_ini_from_graph

    ini = build_ini_from_graph(graph)
    rendered = HalGenerator(hal_type="remora").render(ini)

    assert "loadrt remora-xyz chip_type=STM32F429" in rendered
    assert "remora.stepgen.00" in rendered


def test_hal_generator_parallel_template() -> None:
    graph = _graph(steppers={"x": _stepper("x")})
    from modules.machineconfig.compilers.ini_generator import build_ini_from_graph

    ini = build_ini_from_graph(graph)
    rendered = HalGenerator(hal_type="parallel").render(ini)

    assert "loadrt stepgen step_type=0,0,0" in rendered
    assert "stepgen.0" in rendered
    assert "remora.stepgen" not in rendered