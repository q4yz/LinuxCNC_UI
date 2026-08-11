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

from ..models import Extruder, MachineConfigGraph
from ..parser import derive_fan_name
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
        "Name": "reset_pin",
        "Thread": "Servo",
        "Type": "Reset Pin",
        "Comment": "Reset pin",
        "Pin": "PC_15",
    }


def _stepgen_module(
    name: str,
    joint_number: int,
    axis_letter: str,
    step_pin: str | None,
    dir_pin: str | None,
    enable_pin: str | None,
    comment_override: str | None = None,
) -> dict[str, Any]:
    """Build a Stepgen module for one joint.

    ``name`` is the unique symbolic handle (e.g. ``stepgen_x``)
    derived from the hardware.json id; downstream HAL/Python
    controllers address the module by this name.
    ``comment_override`` lets the caller pass a pre-formatted comment
    (e.g. ``"Extruder - Joint 3 step generator"``) instead of the
    default ``<AXIS> DRIVER<n> - Joint <n> step generator``.
    """
    if comment_override is None:
        comment_override = (
            f"{axis_letter.upper()} DRIVER{joint_number} - "
            f"Joint {joint_number} step generator"
        )
    return {
        "Name": name,
        "Thread": "Base",
        "Type": "Stepgen",
        "Comment": comment_override,
        "Joint Number": joint_number,
        "Step Pin": klipper_to_remora_pin(step_pin),
        "Direction Pin": klipper_to_remora_pin(dir_pin),
        "Enable Pin": klipper_to_remora_pin(enable_pin),
    }


def _tmc2209_module(
    name: str,
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
        "Name": name,
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
    name: str,
    comment: str,
    pin: str | None,
    data_bit: int,
) -> dict[str, Any] | None:
    """Build a Digital Pin module for an endstop."""
    if pin is None:
        return None
    return {
        "Name": name,
        "Thread": "Servo",
        "Type": "Digital Pin",
        "Comment": comment,
        "Pin": klipper_to_remora_pin(pin),
        "Mode": "Input",
        "Data Bit": data_bit,
    }


def _temperature_module(
    name: str,
    comment: str,
    pv_index: int,
    sensor_pin: str | None,
    sensor_type: str | None,
) -> dict[str, Any] | None:
    """Build a Temperature module for a heater."""
    if sensor_pin is None:
        return None
    # Try to derive the beta coefficient from the sensor_type string
    # (the goal uses 3950 for ``Generic 3950``; default to 3990 for
    # unknown types so the firmware still calibrates reasonably).
    beta = 3990
    if sensor_type:
        for token in sensor_type.split():
            if token.isdigit() and len(token) == 4 and token.startswith("3"):
                beta = int(token)
                break
    return {
        "Name": name,
        "Thread": "Servo",
        "Type": "Temperature",
        "Comment": comment,
        "PV[i]": pv_index,
        "Sensor": sensor_type or "Thermistor",
        "Thermistor": {
            "Pin": klipper_to_remora_pin(sensor_pin),
            "beta": beta,
            "r0": 100000,
            "t0": 25,
        },
    }


def _pwm_module(
    name: str,
    comment: str,
    sp_index: int,
    pwm_pin: str | None,
    pwm_max: int | None = None,
) -> dict[str, Any] | None:
    """Build a PWM module for a heater or fan.

    ``name`` is the symbolic handle (e.g. ``pwm_heater_bed`` or
    ``pwm_fan_part_cooling``) the HAL uses to wire the SP[i] index
    to a named signal.
    """
    if pwm_pin is None:
        return None
    module = {
        "Name": name,
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
    name: str,
    comment: str,
    sp_index: int,
    servo_pin: str | None,
) -> dict[str, Any] | None:
    """Build an RCServo module for a probe."""
    if servo_pin is None:
        return None
    return {
        "Name": name,
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

    Every module carries a ``Name`` field derived from the
    :mod:`backend.modules.machineconfig.models.hardware_json_models`
    record id. The HAL/Python layer addresses modules by these
    names; the positional ``SP[i]`` / ``PV[i]`` indices stay because
    Remora firmware requires them.

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
            # Find the original stepper for this joint. Cartesian
            # joints look up by axis letter; the extruder (axis
            # letter ``A``) is the unique ``Extruder`` record on the
            # heaters dict and carries its own stepper fields.
            stepper = graph.steppers.get(axis.letter.lower())
            extruder_record = None
            if stepper is None:
                for name, s in graph.steppers.items():
                    if s.axis.upper() == axis.letter:
                        stepper = s
                        break
            if stepper is None and axis.letter.upper() == "A":
                # The extruder lives under heaters — pull the first
                # ``Extruder`` instance as the canonical stepper source.
                for h in graph.heaters.values():
                    if isinstance(h, Extruder):
                        extruder_record = h
                        break

            # Joint 0..N-1 share the canonical Klipper stepper; the
            # extruder (Joint N) gets its own stepgen module from the
            # extruder record.
            step_pin = stepper.step_pin if stepper else None
            dir_pin = stepper.dir_pin if stepper else None
            enable_pin = stepper.enable_pin if stepper else None
            if extruder_record is not None:
                step_pin = extruder_record.step_pin
                dir_pin = extruder_record.dir_pin
                enable_pin = extruder_record.enable_pin

            if step_pin is not None or stepper is not None or extruder_record is not None:
                # The stepgen ``Name`` matches the hardware.json stepper id
                # (``stepper_x`` for Cartesian joints, ``extruder`` for
                # the extruder joint).
                if extruder_record is not None:
                    stepgen_name = "extruder"
                    axis_label = "Extruder"
                else:
                    stepgen_name = stepper.section_name
                    axis_label = axis.letter.upper()
                # Stepgen comment: ``<axis> - Joint <n> step generator``
                # (the goal uses this shorter form; the DRIVER<n> prefix
                # was historical Klipper output).
                stepgen_comment = (
                    f"{axis_label} - Joint {joint_number} step generator"
                )
                modules.append(
                    _stepgen_module(
                        stepgen_name,
                        joint_number,
                        axis.letter,
                        step_pin,
                        dir_pin,
                        enable_pin,
                        comment_override=stepgen_comment,
                    )
                )

                # TMC2209 module (if configured). ``Name`` follows the
                # ``driver_<stepper_id>`` convention used by
                # ``hardware.json`` so HAL can wire Remora signals by
                # the same handle. The TMC2209 -> stepper link is
                # keyed by the Klipper ``[tmc2209 stepper_X]`` section
                # header, which matches the stepper ``section_name``.
                tmc_section = stepper.section_name if stepper else None
                tmc = (
                    _tmc2209_module(
                        f"driver_{tmc_section}",
                        joint_number,
                        axis.letter,
                        getattr(graph.tmc2209s.get(tmc_section), "uart_pin", None)
                        if tmc_section
                        else None,
                        getattr(graph.tmc2209s.get(tmc_section), "run_current", None)
                        if tmc_section
                        else None,
                        getattr(stepper, "microsteps", None) if stepper else None,
                        getattr(graph.tmc2209s.get(tmc_section), "stealthchop_threshold", None)
                        if tmc_section
                        else None,
                    )
                    if tmc_section and tmc_section in graph.tmc2209s
                    else None
                )
                if tmc:
                    modules.append(tmc)

                # Digital Pin module for endstop — ``Name`` matches
                # the hardware.json endstop record id (``endstop_X_MIN``
                # / ``homing_X_MIN`` etc.) so the HAL can reference the
                # exact switch by handle. The endstop switch name
                # (e.g. ``X_MIN``) is derived from the Klipper
                # ``endstop_switch`` section; we fall back to
                # ``<AXIS>_MIN`` when no explicit section is declared.
                endstop_switch_name = (
                    next(iter(graph.endstop_switches.keys()), None)
                    if graph.endstop_switches
                    else None
                )
                switch_suffix = (
                    endstop_switch_name
                    if endstop_switch_name
                    else f"{axis.letter.upper()}_MIN"
                )
                endstop_comment = (
                    f"{axis.letter.upper()} endstop ({stepper.endstop_pin})"
                    if stepper and stepper.endstop_pin
                    else f"{axis.letter.upper()} endstop"
                )
                dp_name = f"endstop_{switch_suffix}"
                dp = _digital_pin_module(
                    dp_name,
                    endstop_comment,
                    stepper.endstop_pin if stepper else None,
                    data_bit,
                )
                if dp:
                    modules.append(dp)
                    data_bit += 1

            joint_number += 1

    # 3. Temperature + PWM modules for heaters
    # Walk the graph's heaters dict in canonical name order. Extruders
    # are indexed as "Ext 0", "Ext 1", ... in the order they appear
    # in the source file (so the first extruder is always Ext 0).
    # Non-extruder heaters keep their canonical name as the Remora
    # module comment.
    sorted_heaters = sorted(graph.heaters.values(), key=lambda h: h.name)

    extruder_index = 0
    for heater in sorted_heaters:
        if isinstance(heater, Extruder):
            label = "Extruder"
            comment = f"{label} temperature sensor"
            pwm_comment = f"{label} heater PWM"
            extruder_index += 1
        else:
            # ``[heater_bed]`` -> ``Heated Bed`` for the sensor
            # comment; the PWM comment uses ``Bed`` (matches the
            # goal's hand-written convention where ``Bed heater PWM``
            # is shorter than ``Heated Bed heater PWM``).
            label = heater.name
            if label.startswith("heater_"):
                rest = label[len("heater_"):]
                if rest == "bed":
                    sensor_label = "Heated Bed"
                    pwm_label = "Bed"
                else:
                    sensor_label = rest.replace("_", " ").title()
                    pwm_label = sensor_label
            else:
                sensor_label = label.replace("_", " ").title()
                pwm_label = sensor_label
            comment = f"{sensor_label} temperature sensor"
            pwm_comment = f"{pwm_label} heater PWM"

        # ``Name`` derives from the canonical hardware.json id
        # (``heater_bed`` -> ``temp_bed`` + ``pwm_heater_bed``).
        temp_name = (
            f"temp_{heater.name.removeprefix('heater_')}"
            if heater.name.startswith("heater_")
            else f"temp_{heater.name}"
        )
        pwm_name = f"pwm_{heater.name}"

        temp = _temperature_module(
            temp_name,
            comment,
            pv_index,
            heater.sensor_pin,
            heater.sensor_type,
        )
        if temp:
            modules.append(temp)
            pv_index += 1

        pwm = _pwm_module(
            pwm_name,
            pwm_comment,
            sp_index,
            heater.heater_pin,
        )
        if pwm:
            modules.append(pwm)
            sp_index += 1

    # 4. Standalone ``[fan]`` / ``[fan_generic]`` sections. These
    # follow the heater PWMs and reuse the same SP[i] counter so the
    # indexing stays contiguous. ``Name`` is the canonical fan id
    # (``fan_part_cooling``) — the HAL binds the matching symbolic
    # signal to the same SP[i] index.
    sorted_fans = sorted(graph.fans.values(), key=lambda f: f.name)
    for fan in sorted_fans:
        if fan.max_power is not None:
            # 0.0–1.0 → 0–255. Round so the integer is stable across
            # float formatting.
            pwm_max = max(0, min(255, round(fan.max_power * 255)))
        else:
            # Default 50% duty-cycle cap when the user didn't pin
            # ``max_power`` on the Klipper side. The goal uses 128
            # for the part-cooling fan.
            pwm_max = 128
        pwm = _pwm_module(
            f"pwm_{fan.name}",
            f"{fan.name.replace('_', ' ')} PWM",
            sp_index,
            fan.pin,
            pwm_max=pwm_max,
        )
        if pwm:
            modules.append(pwm)
            sp_index += 1

    # 5. Spindle PWM (if configured)
    if graph.spindle_analog and graph.spindle_analog.pwm_pin:
        pwm = _pwm_module(
            "spindle_pwm",
            "Spindle PWM",
            sp_index,
            graph.spindle_analog.pwm_pin,
        )
        if pwm:
            modules.append(pwm)
            sp_index += 1

    # 6. RCServo for probe (if configured)
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