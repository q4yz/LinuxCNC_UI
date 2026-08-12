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
    MCU,
    Printer,
    Stepper,
)


# --------------------------------------------------------------------- #
# Fixtures / helpers                                                     #
# --------------------------------------------------------------------- #


#: Default remora MCU used by the legacy tests. Mirrors the
#: production defaults (empty ``[mcu]`` -> remora-spi + OCTOPUS)
#: so the assertions still reflect the byte-for-byte goal output.
_DEFAULT_REMORA_MCU = MCU(connection="remora-spi", board="BIGTREETECH OCTOPUS")


def _graph(
    printer: Printer | None = None,
    steppers: dict[str, Stepper] | None = None,
    mcus: dict[str, MCU] | None = None,
) -> MachineConfigGraph:
    return MachineConfigGraph(
        printer=printer,
        steppers=steppers or {},
        mcus=mcus if mcus is not None else {"mcu": _DEFAULT_REMORA_MCU},
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


def _full_klipper_payload() -> MachineConfigGraph:
    """A minimal Klipper profile: X stepper + Y stepper + Z stepper.

    Used by the ``config.txt`` Name-field tests below; the steppers
    are positional so the assertions can target specific ``Name``
    values without depending on the heater / fan graph.
    """
    graph = MachineConfigGraph(
        printer=Printer(), mcus={"mcu": _DEFAULT_REMORA_MCU}
    )
    graph.steppers["x"] = _stepper(axis="x", position_max=200.0)
    graph.steppers["y"] = _stepper(axis="y", position_max=200.0)
    graph.steppers["z"] = _stepper(axis="z", position_max=200.0, rotation_distance=8.0)
    return graph


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

    assert payload["version"] == "2.0"
    assert payload["machine"] == "test_machine"
    assert payload["kinematics"] == "cartesian"
    assert payload["hal_type"] == "remora"
    assert len(payload["steppers"]) == 3
    # The v2 shape keys steppers by id (derived from the section name),
    # not by axis letter. The axis letter is recoverable from the
    # axes list, not stored on the stepper itself.
    assert payload["steppers"][0]["id"] == "stepper_x"
    assert payload["steppers"][0]["rotation_distance"] == 40.0
    assert payload["steppers"][2]["id"] == "stepper_z"
    assert payload["steppers"][2]["rotation_distance"] == 8.0


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


def test_hardware_json_v2_carries_heater_and_extruder_tools(tmp_path):
    """The production ``KlipperToLinuxCNCCompiler`` populates
    ``hardware.json`` v2 with both heater-shaped sections.

    Both ``[heater_bed]`` and ``[extruder]`` declarations become a
    :class:`Tool` record (with type ``heated_bed`` / ``extruder``)
    plus a :class:`TemperatureSensor` row that the chart can attach
    to. The fixture's extruder section carries full stepper data so
    the parser can construct an :class:`Extruder` record rather than
    silently degrading the graph.

    This is the v2 replacement for the historical
    ``HalCompiler._generate_remora_json`` test. The fixture omits the
    ``[mcu]`` block so the remora MCU is absent; the new compiler
    deletes the file in that case (no stale ``hardware.json``
    payload), so we drive the hardware.json generator directly to
    validate the shape without going through the file-system dance.
    """
    from modules.machineconfig.compilers.hardware_json_generator import (
        build_hardware_json,
    )
    from modules.machineconfig.parser import parse_config

    cfg_path = _write_machine_cfg(
        tmp_path,
        (
            "[mcu]\nconnection: remora-spi\nboard: BIGTREETECH OCTOPUS\n"
            "[heater_bed]\n"
            "heater_pin: PB7\n"
            "sensor_pin: PA0\n"
            "max_temp: 120\n"
            "control: watermark\n"
            "sensor_type: NTC 100K\n"
            "\n[extruder]\n"
            "heater_pin: PA2\n"
            "sensor_pin: PA1\n"
            "max_temp: 250\n"
            "control: pid\n"
            "sensor_type: PT1000\n"
            "pid_Kp: 22.2\n"
            "pid_Ki: 1.08\n"
            "pid_Kd: 114\n"
            "step_pin: PE2\n"
            "dir_pin: PE3\n"
            "enable_pin: PE4\n"
            "microsteps: 16\n"
            "rotation_distance: 33.0\n"
        ),
    )
    graph = parse_config(cfg_path)
    payload = build_hardware_json(graph, "v2_heater_test")

    # Two tool entries (one per heater-shaped section). v2 carries
    # the legacy ``max_temp`` / ``control`` keys on the tool itself;
    # the historical ``heaters`` field no longer exists.
    by_id = {entry["id"]: entry for entry in payload["tools"]}
    assert set(by_id.keys()) == {"heater_bed", "heater_extruder"}

    bed = by_id["heater_bed"]
    assert bed["type"] == "heated_bed"
    assert bed["control"] == "watermark"
    assert bed["max_temp"] == 120.0

    extruder = by_id["heater_extruder"]
    assert extruder["type"] == "extruder"
    assert extruder["control"] == "pid"
    assert extruder["max_temp"] == 250.0

    # The temperature_sensors list mirrors the two heater-shaped
    # sections; the sensor ids are derived from the section header
    # (``bed`` + ``extruder``).
    sensor_ids = {entry["id"] for entry in payload["temperature_sensors"]}
    assert sensor_ids == {"bed", "extruder"}
    bed_sensor = next(
        s for s in payload["temperature_sensors"] if s["id"] == "bed"
    )
    assert bed_sensor["type"] == "NTC 100K"


def test_hardware_json_v2_empty_when_no_heaters(tmp_path):
    """A profile with no ``[extruder]`` / ``[heater_bed]`` yields
    empty tool and temperature-sensor lists.

    Same v2-replacement rationale as the populated counterpart above:
    drives the production generator directly so the v2 shape is
    verified independently of the (now retired) ``HalCompiler``.
    """
    from modules.machineconfig.compilers.hardware_json_generator import (
        build_hardware_json,
    )
    from modules.machineconfig.parser import parse_config

    cfg_path = _write_machine_cfg(
        tmp_path,
        "[mcu]\nconnection: remora-spi\nboard: BIGTREETECH OCTOPUS\n"
        "[printer]\nkinematics: cartesian\nmax_velocity: 300\n",
    )
    graph = parse_config(cfg_path)
    payload = build_hardware_json(graph, "empty_heater_test")

    assert payload["tools"] == []
    assert payload["temperature_sensors"] == []


# --------------------------------------------------------------------- #
# Phase 3 — config.txt Name field + fan PWM modules                      #
# --------------------------------------------------------------------- #


def test_config_txt_emits_name_field_on_every_module() -> None:
    """Every module in ``config.txt`` carries a ``Name`` field.

    The Name is the symbolic handle the HAL/Python layer uses to
    address the module; it is derived from the hardware.json id.
    """
    payload = _full_klipper_payload()
    config_txt = build_config_txt(payload, "ender3")

    names = [m["Name"] for m in config_txt["Modules"]]
    # Reset Pin is always present.
    assert "reset_pin" in names
    # Each axis gets a stepgen module named after the Klipper section.
    assert any(n == "stepper_x" for n in names)
    assert any(n == "stepper_y" for n in names)
    assert any(n == "stepper_z" for n in names)
    # TMC2209 modules (none in this minimal graph — no uart_pin) are
    # absent by design; the assertion is implicit.

    # Heaters get temp_/pwm_ handles. The minimal payload has no
    # heaters; the assertion below checks the symbol-shape exists.
    # A fuller profile would add them via _graph.
    assert all(isinstance(n, str) and n for n in names), names


def test_config_txt_emits_fan_pwm_module_with_max_power() -> None:
    """``[fan_generic part_cooling]`` becomes a PWM module with PWM Max.

    ``max_power: 0.5`` becomes ``PWM Max: 128`` (0.5 * 255 rounded).
    """
    from modules.machineconfig.models import Fan, Printer, Stepper

    graph = MachineConfigGraph(
        printer=Printer(), mcus={"mcu": _DEFAULT_REMORA_MCU}
    )
    graph.fans["fan_generic_part_cooling"] = Fan(
        name="fan_generic_part_cooling",
        pin="PA8",
        max_power=0.5,
    )

    config_txt = build_config_txt(graph, "fan-test")
    pwm_modules = [m for m in config_txt["Modules"] if m["Type"] == "PWM"]
    assert len(pwm_modules) == 1
    fan_pwm = pwm_modules[0]
    assert fan_pwm["Name"] == "pwm_fan_generic_part_cooling"
    assert fan_pwm["PWM Max"] == 128
    assert fan_pwm["SP[i]"] == 0
    assert fan_pwm["PWM Pin"] == "PA_8"


def test_config_txt_fan_follows_heater_pwm_indices() -> None:
    """A standalone fan gets the next SP[i] after the heater PWMs."""
    from modules.machineconfig.models import Extruder, Fan, Heater, Printer, Stepper

    graph = MachineConfigGraph(
        printer=Printer(), mcus={"mcu": _DEFAULT_REMORA_MCU}
    )
    # Heater BED (PV[0], SP[0])
    graph.heaters["heater_bed"] = Heater(
        name="heater_bed",
        heater_pin="PA1",
        sensor_pin="PA3",
        sensor_type="NTC 100K",
        control="watermark",
    )
    # Extruder (PV[1], SP[1])
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
    # Part-cooling fan (SP[2])
    graph.fans["fan_part_cooling"] = Fan(
        name="fan_part_cooling",
        pin="PA8",
        max_power=1.0,
    )

    config_txt = build_config_txt(graph, "ender3")
    pwm_modules = [m for m in config_txt["Modules"] if m["Type"] == "PWM"]
    sp_indices = [m["SP[i]"] for m in pwm_modules]
    assert sp_indices == [0, 1, 2]
    pwm_names = [m["Name"] for m in pwm_modules]
    # Heaters are sorted alphabetically by canonical name (``extruder``
    # < ``heater_bed``) so ``pwm_extruder`` lands on SP[0] and the
    # part-cooling fan on SP[2] (after the heater PWMs).
    assert pwm_names == [
        "pwm_extruder",
        "pwm_heater_bed",
        "pwm_fan_part_cooling",
    ]