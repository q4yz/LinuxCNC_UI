"""Generate ``config.txt`` — the Remora board JSON payload.

``config.txt`` is the file that gets flashed to the Remora board.
It contains a ``Modules`` array with different module types:

* ``Reset Pin`` — board reset pin (static)
* ``Stepgen`` — step generator with joint number, step/dir/enable pins
* ``TMC2209`` — TMC driver with RX pin, RSense, current, microsteps
* ``Digital Pin`` — digital input/output with pin, mode, data bit
* ``Temperature`` — temperature sensor with PV index, thermistor params
* ``PWM`` — PWM output with SP index, PWM pin, optional PWM max
* ``RCServo`` — RC servo with SP index, servo pin

The generator walks the parsed Klipper graph and emits modules
dynamically based on what's configured. Missing sections (e.g. no
extruder, no fans) simply result in fewer modules.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from ..models import MachineConfigGraph
from .axis_builder import AxisBuilder

logger = logging.getLogger("backend.modules.machineconfig.compilers.config_txt_generator")


# --------------------------------------------------------------------- #
# Pin conversion                                                         #
# --------------------------------------------------------------------- #


def klipper_to_remora_pin(pin: str | None) -> str | None:
    """Convert Klipper pin format (PF13, !PF13, or ^PF13) to Remora format (PF_13).

    The Remora JSON uses underscores between port and pin number.
    Active-low markers (``!``) and pull-up markers (``^``) are
    stripped — the Remora firmware handles polarity and pull-ups
    internally.
    """
    if not pin:
        return None
    # Strip active-low and pull-up markers
    if pin.startswith("!") or pin.startswith("^"):
        pin = pin[1:]
    # Add underscore between port and pin number
    match = re.match(r"^([A-Z]+)(\d+)$", pin)
    if match:
        port, num = match.groups()
        return f"{port}_{num}"
    return pin


def remora_to_klipper_pin(pin: str | None) -> str | None:
    """Convert Remora pin format (PF_13) to Klipper format (PF13)."""
    if not pin:
        return None
    return pin.replace("_", "")


# --------------------------------------------------------------------- #
# Module builders                                                        #
# --------------------------------------------------------------------- #


def _reset_pin_module() -> dict[str, Any]:
    """Static reset pin module."""
    return {
        "Thread": "Servo",
        "Type": "Reset Pin",
        "Comment": "Reset pin",
        "Pin": "PC_15",
    }


def _stepgen_module(
    joint_number: int,
    axis_letter: str,
    step_pin: str | None,
    dir_pin: str | None,
    enable_pin: str | None,
) -> dict[str, Any]:
    """Build a Stepgen module for one joint."""
    return {
        "Thread": "Base",
        "Type": "Stepgen",
        "Comment": f"{axis_letter.upper()} DRIVER{joint_number} - Joint {joint_number} step generator",
        "Joint Number": joint_number,
        "Step Pin": klipper_to_remora_pin(step_pin),
        "Direction Pin": klipper_to_remora_pin(dir_pin),
        "Enable Pin": klipper_to_remora_pin(enable_pin),
    }


def _tmc2209_module(
    joint_number: int,
    axis_letter: str,
    uart_pin: str | None,
    run_current: float | None,
    microsteps: int | None,
    stealthchop_threshold: int | None,
) -> dict[str, Any] | None:
    """Build a TMC2209 module for one joint.

    Returns None if the TMC2209 section is not configured for this
    stepper.
    """
    if uart_pin is None:
        return None
    return {
        "Thread": "On load",
        "Type": "TMC2209",
        "Comment": f"{axis_letter.upper()} - Joint {joint_number} TMC driver",
        "RX pin": klipper_to_remora_pin(uart_pin),
        "RSense": 0.11,
        "Current": int((run_current or 0.8) * 1000),  # A → mA
        "Microsteps": microsteps or 16,
        "Stealth chop": "on" if (stealthchop_threshold or 999999) > 0 else "off",
        "Stall sensitivity": 0,
    }


def _digital_pin_module(
    comment: str,
    pin: str | None,
    data_bit: int,
) -> dict[str, Any] | None:
    """Build a Digital Pin module for an endstop."""
    if pin is None:
        return None
    return {
        "Thread": "Servo",
        "Type": "Digital Pin",
        "Comment": comment,
        "Pin": klipper_to_remora_pin(pin),
        "Mode": "Input",
        "Data Bit": data_bit,
    }


def _temperature_module(
    comment: str,
    pv_index: int,
    sensor_pin: str | None,
    sensor_type: str | None,
) -> dict[str, Any] | None:
    """Build a Temperature module for a heater."""
    if sensor_pin is None:
        return None
    return {
        "Thread": "Servo",
        "Type": "Temperature",
        "Comment": comment,
        "PV[i]": pv_index,
        "Sensor": sensor_type or "Thermistor",
        "Thermistor": {
            "Pin": klipper_to_remora_pin(sensor_pin),
            "beta": 3990,
            "r0": 100000,
            "t0": 25,
        },
    }


def _pwm_module(
    comment: str,
    sp_index: int,
    pwm_pin: str | None,
    pwm_max: int | None = None,
) -> dict[str, Any] | None:
    """Build a PWM module for a heater or fan."""
    if pwm_pin is None:
        return None
    module = {
        "Thread": "Servo",
        "Type": "PWM",
        "Comment": comment,
        "SP[i]": sp_index,
        "PWM Pin": klipper_to_remora_pin(pwm_pin),
    }
    if pwm_max is not None:
        module["PWM Max"] = pwm_max
    return module


def _rcservo_module(
    comment: str,
    sp_index: int,
    servo_pin: str | None,
) -> dict[str, Any] | None:
    """Build an RCServo module for a probe."""
    if servo_pin is None:
        return None
    return {
        "Thread": "Base",
        "Type": "RCServo",
        "Comment": comment,
        "SP[i]": sp_index,
        "Servo Pin": klipper_to_remora_pin(servo_pin),
    }


# --------------------------------------------------------------------- #
# Main generator                                                         #
# --------------------------------------------------------------------- #


def build_config_txt(graph: MachineConfigGraph, machine_name: str) -> dict[str, Any]:
    """Build the config.txt payload from a parsed Klipper graph.

    Parameters
    ----------
    graph:
        Parsed Klipper profile.
    machine_name:
        The machine name (from the source file stem).

    Returns
    -------
    dict
        The config.txt payload, ready to be serialized.
    """
    axes = AxisBuilder(graph).build()

    modules: list[dict[str, Any]] = []

    # 1. Reset pin (static)
    modules.append(_reset_pin_module())

    # 2. Stepgen + TMC2209 modules (per joint)
    joint_number = 0
    data_bit = 0
    pv_index = 0
    sp_index = 0

    for axis in axes:
        for joint in axis.joints:
            # Find the original stepper for this joint
            stepper = graph.steppers.get(axis.letter.lower())
            if stepper is None:
                for name, s in graph.steppers.items():
                    if s.axis.upper() == axis.letter:
                        stepper = s
                        break

            if stepper:
                # Stepgen module
                modules.append(
                    _stepgen_module(
                        joint_number,
                        axis.letter,
                        stepper.step_pin,
                        stepper.dir_pin,
                        stepper.enable_pin,
                    )
                )

                # TMC2209 module (if configured)
                tmc = _tmc2209_module(
                    joint_number,
                    axis.letter,
                    getattr(stepper, "uart_pin", None),
                    getattr(stepper, "run_current", None),
                    stepper.microsteps,
                    getattr(stepper, "stealthchop_threshold", None),
                )
                if tmc:
                    modules.append(tmc)

                # Digital Pin module for endstop
                endstop_comment = f"{axis.letter.upper()} min DIAG{data_bit}"
                dp = _digital_pin_module(
                    endstop_comment,
                    stepper.endstop_pin,
                    data_bit,
                )
                if dp:
                    modules.append(dp)
                    data_bit += 1

            joint_number += 1

    # 3. Temperature + PWM modules for heaters
    if graph.extruder:
        temp = _temperature_module(
            "Ext 0 temperature sensor",
            pv_index,
            graph.extruder.sensor_pin,
            graph.extruder.sensor_type,
        )
        if temp:
            modules.append(temp)
            pv_index += 1

        pwm = _pwm_module(
            "Ext0 heater PWM",
            sp_index,
            graph.extruder.heater_pin,
        )
        if pwm:
            modules.append(pwm)
            sp_index += 1

    if graph.heater_bed:
        temp = _temperature_module(
            "Heated Bed temperature sensor",
            pv_index,
            graph.heater_bed.sensor_pin,
            graph.heater_bed.sensor_type,
        )
        if temp:
            modules.append(temp)
            pv_index += 1

        pwm = _pwm_module(
            "Bed heater PWM",
            sp_index,
            graph.heater_bed.heater_pin,
        )
        if pwm:
            modules.append(pwm)
            sp_index += 1

    # 4. Spindle PWM (if configured)
    if graph.spindle and graph.spindle.pwm_pin:
        pwm = _pwm_module(
            "Spindle PWM",
            sp_index,
            graph.spindle.pwm_pin,
        )
        if pwm:
            modules.append(pwm)
            sp_index += 1

    # 5. RCServo for probe (if configured)
    # TODO: add probe support to parser when needed

    payload = {
        "Board": "BIGTREETECH OCTOPUS",
        "Modules": modules,
    }

    logger.info(
        "config.txt: %d modules (%d stepgen, %d tmc2209, %d digital pin, %d temperature, %d pwm)",
        len(modules),
        sum(1 for m in modules if m["Type"] == "Stepgen"),
        sum(1 for m in modules if m["Type"] == "TMC2209"),
        sum(1 for m in modules if m["Type"] == "Digital Pin"),
        sum(1 for m in modules if m["Type"] == "Temperature"),
        sum(1 for m in modules if m["Type"] == "PWM"),
    )
    return payload


def write_config_txt(
    path: Path,
    graph: MachineConfigGraph,
    machine_name: str,
) -> None:
    """Write config.txt to disk."""
    payload = build_config_txt(graph, machine_name)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "build_config_txt",
    "klipper_to_remora_pin",
    "remora_to_klipper_pin",
    "write_config_txt",
]