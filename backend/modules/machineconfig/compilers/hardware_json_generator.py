"""Generate ``hardware.json`` — the backend's high-level hardware overview.

``hardware.json`` is the canonical record of every pin, stepper,
heater, and fan the backend knows about. It is derived from the
parsed Klipper graph at compile time and consumed by everything
that needs to query the hardware (deployment tools, the console,
future Remora firmware flasher) without parsing the raw config
again.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..models import MachineConfigGraph
from .axis_builder import AxisBuilder, stepgen_scale

logger = logging.getLogger("backend.modules.machineconfig.compilers.hardware_json_generator")


def _fmt_float(value: float | None) -> float | None:
    """Format a float, returning None for missing values."""
    if value is None:
        return None
    return round(float(value), 4)


def _stepper_entry(stepper, joint_number: int) -> dict[str, Any]:
    """Build a stepper entry for hardware.json."""
    return {
        "axis": stepper.axis,
        "joint_number": joint_number,
        "step_pin": stepper.step_pin,
        "dir_pin": stepper.dir_pin,
        "enable_pin": stepper.enable_pin,
        "microsteps": stepper.microsteps,
        "rotation_distance": _fmt_float(stepper.rotation_distance),
        "scale": _fmt_float(stepgen_scale(stepper)),
        "position_min": _fmt_float(getattr(stepper, "position_min", None)),
        "position_max": _fmt_float(stepper.position_max),
        "position_endstop": _fmt_float(stepper.position_endstop),
        "homing_speed": _fmt_float(getattr(stepper, "homing_speed", None)),
    }


def _heater_entry(name: str, heater) -> dict[str, Any]:
    """Build a heater entry for hardware.json."""
    return {
        "name": name,
        "heater_pin": heater.heater_pin,
        "sensor_type": heater.sensor_type,
        "sensor_pin": heater.sensor_pin,
        "control": heater.control,
        "min_temp": heater.min_temp,
        "max_temp": heater.max_temp,
    }


def _endstop_entry(name: str, switch) -> dict[str, Any]:
    """Build an endstop entry for hardware.json."""
    return {
        "name": name,
        "stepper": switch.stepper.axis,
        "pin": switch.pin,
        "position": _fmt_float(switch.position),
        "type": switch.type,
    }


def build_hardware_json(graph: MachineConfigGraph, machine_name: str) -> dict[str, Any]:
    """Build the hardware.json payload from a parsed Klipper graph.

    Parameters
    ----------
    graph:
        Parsed Klipper profile.
    machine_name:
        The machine name (from the source file stem).

    Returns
    -------
    dict
        The hardware.json payload, ready to be serialized.
    """
    axes = AxisBuilder(graph).build()

    steppers = []
    joint_number = 0
    for axis in axes:
        for joint in axis.joints:
            # Find the original stepper for this joint
            stepper = graph.steppers.get(axis.letter.lower())
            if stepper is None:
                # Try alternate section names (e.g., "y1" for dual-motor Y)
                for name, s in graph.steppers.items():
                    if s.axis.upper() == axis.letter:
                        stepper = s
                        break
            if stepper:
                steppers.append(_stepper_entry(stepper, joint_number))
            joint_number += 1

    heaters = []
    if graph.extruder:
        heaters.append(_heater_entry("extruder", graph.extruder))
    if graph.heater_bed:
        heaters.append(_heater_entry("heater_bed", graph.heater_bed))

    endstops = [
        _endstop_entry(name, switch)
        for name, switch in graph.endstop_switches.items()
    ]

    # Extract hal_type from MCU section if present
    hal_type = "remora"  # default
    if hasattr(graph, "mcu") and graph.mcu:
        hal_type = getattr(graph.mcu, "hal_type", "remora")

    payload = {
        "generated": True,
        "machine": machine_name,
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": graph.printer.kinematics if graph.printer else "cartesian",
        "hal_type": hal_type,
        "steppers": steppers,
        "heaters": heaters,
        "endstops": endstops,
        "fans": [],  # TODO: populate from [fan] sections when parser supports them
        "note": "Populate steppers/heaters from the Klipper source as needed.",
    }

    logger.info(
        "hardware.json: %d steppers, %d heaters, %d endstops",
        len(steppers),
        len(heaters),
        len(endstops),
    )
    return payload


def write_hardware_json(
    path: Path,
    graph: MachineConfigGraph,
    machine_name: str,
) -> None:
    """Write hardware.json to disk."""
    payload = build_hardware_json(graph, machine_name)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


__all__ = ["build_hardware_json", "write_hardware_json"]