"""Tests for the hardware.json and config.txt generators."""

from __future__ import annotations

import json
from pathlib import Path

from modules.machineconfig.compilers.config_txt_generator import (
    build_config_txt,
    klipper_to_remora_pin,
    remora_to_klipper_pin,
)
from modules.machineconfig.compilers.hardware_json_generator import (
    build_hardware_json,
)
from modules.machineconfig.models import (
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
# Pin conversion                                                         #
# --------------------------------------------------------------------- #


def test_klipper_to_remora_pin_basic() -> None:
    assert klipper_to_remora_pin("PF13") == "PF_13"
    assert klipper_to_remora_pin("PG0") == "PG_0"
    assert klipper_to_remora_pin("PC15") == "PC_15"


def test_klipper_to_remora_pin_strips_active_low() -> None:
    assert klipper_to_remora_pin("!PF13") == "PF_13"


def test_klipper_to_remora_pin_strips_pull_up() -> None:
    assert klipper_to_remora_pin("^PC0") == "PC_0"


def test_klipper_to_remora_pin_none() -> None:
    assert klipper_to_remora_pin(None) is None


def test_remora_to_klipper_pin() -> None:
    assert remora_to_klipper_pin("PF_13") == "PF13"
    assert remora_to_klipper_pin("PG_0") == "PG0"


# --------------------------------------------------------------------- #
# hardware.json                                                          #
# --------------------------------------------------------------------- #


def test_hardware_json_basic() -> None:
    graph = _graph(
        printer=Printer(max_velocity=250.0, max_accel=750.0),
        steppers={
            "x": _stepper("x"),
            "y": _stepper("y"),
            "z": _stepper("z", rotation_distance=8.0),
        },
    )
    payload = build_hardware_json(graph, "test_machine")

    assert payload["machine"] == "test_machine"
    assert payload["kinematics"] == "cartesian"
    assert payload["hal_type"] == "remora"
    assert len(payload["steppers"]) == 3
    assert payload["steppers"][0]["axis"] == "x"
    assert payload["steppers"][0]["scale"] == 80.0
    assert payload["steppers"][2]["axis"] == "z"
    assert payload["steppers"][2]["scale"] == 400.0


def test_hardware_json_includes_pins() -> None:
    graph = _graph(
        steppers={
            "x": _stepper("x", step_pin="PF13", dir_pin="PF12", enable_pin="!PF14"),
        },
    )
    payload = build_hardware_json(graph, "test")

    assert payload["steppers"][0]["step_pin"] == "PF13"
    assert payload["steppers"][0]["dir_pin"] == "PF12"
    assert payload["steppers"][0]["enable_pin"] == "!PF14"


# --------------------------------------------------------------------- #
# config.txt                                                             #
# --------------------------------------------------------------------- #


def test_config_txt_basic() -> None:
    graph = _graph(
        printer=Printer(max_velocity=250.0, max_accel=750.0),
        steppers={
            "x": _stepper("x", step_pin="PF13", dir_pin="PF12", enable_pin="!PF14"),
            "y": _stepper("y", step_pin="PG0", dir_pin="PG1", enable_pin="!PF15"),
        },
    )
    payload = build_config_txt(graph, "test")

    assert payload["Board"] == "BIGTREETECH OCTOPUS"
    assert len(payload["Modules"]) > 0

    # Reset pin is always first
    assert payload["Modules"][0]["Type"] == "Reset Pin"
    assert payload["Modules"][0]["Pin"] == "PC_15"

    # Stepgen modules
    stepgens = [m for m in payload["Modules"] if m["Type"] == "Stepgen"]
    assert len(stepgens) == 2
    assert stepgens[0]["Joint Number"] == 0
    assert stepgens[0]["Step Pin"] == "PF_13"
    assert stepgens[0]["Direction Pin"] == "PF_12"
    assert stepgens[0]["Enable Pin"] == "PF_14"  # ! stripped
    assert stepgens[1]["Joint Number"] == 1
    assert stepgens[1]["Step Pin"] == "PG_0"


def test_config_txt_includes_digital_pins() -> None:
    graph = _graph(
        steppers={
            "x": _stepper("x", endstop_pin="^PC0"),
        },
    )
    payload = build_config_txt(graph, "test")

    digital_pins = [m for m in payload["Modules"] if m["Type"] == "Digital Pin"]
    assert len(digital_pins) == 1
    assert digital_pins[0]["Pin"] == "PC_0"  # ^ stripped
    assert digital_pins[0]["Mode"] == "Input"
    assert digital_pins[0]["Data Bit"] == 0


def test_config_txt_skips_missing_sections() -> None:
    """No extruder, no heater_bed ⇒ no Temperature/PWM modules."""

    graph = _graph(steppers={"x": _stepper("x")})
    payload = build_config_txt(graph, "test")

    types = [m["Type"] for m in payload["Modules"]]
    assert "Temperature" not in types
    assert "PWM" not in types
    assert "RCServo" not in types


# --------------------------------------------------------------------- #
# HalCompiler._generate_remora_json — hardware.json heater population    #
# --------------------------------------------------------------------- #


def _write_machine_cfg(tmp_path, body: str):
    """Helper: drop a minimal ``machine.cfg`` and return its path."""
    cfg = tmp_path / "machine.cfg"
    cfg.write_text(body, encoding="utf-8")
    return cfg


def test_hal_compiler_populates_heaters_from_machine_cfg(tmp_path):
    """``HalCompiler._generate_remora_json`` must produce a non-empty
    ``heaters`` array sourced from the parsed ``MachineConfig``
    (issue #97).

    A fixture ``machine.cfg`` declares both an ``[extruder]`` and a
    ``[heater_bed]`` section. The compiled ``hardware.json`` must
    contain both, each with the documented shape
    ``{name, control, max_temp, sensor_type}``. The extruder
    section carries full stepper data so ``MachineConfig.get_heaters``
    constructs an :class:`ExtruderConfig` rather than raising.
    """
    from core.config_manager import MachineConfig
    from services.hal_compiler import HalCompiler

    cfg_path = _write_machine_cfg(
        tmp_path,
        (
            "[heater_bed]\n"
            "max_temp: 120\n"
            "control: watermark\n"
            "sensor_type: NTC 100K\n"
            "\n[extruder]\n"
            "max_temp: 250\n"
            "control: pid\n"
            "sensor_type: PT1000\n"
            "step_pin: PE2\n"
            "dir_pin: PE3\n"
            "enable_pin: PE4\n"
            "microsteps: 16\n"
            "rotation_distance: 33.0\n"
        ),
    )
    config = MachineConfig(str(cfg_path))
    compiler = HalCompiler(config)

    out_path = tmp_path / "hardware.json"
    compiler._generate_remora_json(str(out_path))

    import json

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    by_name = {entry["name"]: entry for entry in payload["heaters"]}
    # Both declared sections must flow through to hardware.json.
    assert set(by_name.keys()) == {"heater_bed", "extruder"}
    # Each entry must carry the documented shape.
    bed = by_name["heater_bed"]
    assert bed["control"] == "watermark"
    assert bed["max_temp"] == 120.0
    assert bed["sensor_type"] == "NTC 100K"
    extruder = by_name["extruder"]
    assert extruder["control"] == "pid"
    assert extruder["max_temp"] == 250.0
    assert extruder["sensor_type"] == "PT1000"


def test_hal_compiler_heaters_empty_when_no_sections(tmp_path):
    """A ``machine.cfg`` without ``[extruder]`` or ``[heater_bed]``
    yields an empty ``heaters`` array (issue #97).
    """
    from core.config_manager import MachineConfig
    from services.hal_compiler import HalCompiler

    cfg_path = _write_machine_cfg(
        tmp_path,
        "[printer]\nkinematics: cartesian\nmax_velocity: 300\n",
    )
    config = MachineConfig(str(cfg_path))
    compiler = HalCompiler(config)

    out_path = tmp_path / "hardware.json"
    compiler._generate_remora_json(str(out_path))

    import json

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["heaters"] == []