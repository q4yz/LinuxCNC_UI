"""Dataclass object graph for parsed machine configurations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(slots=True)
class Printer:
    """Cartesian machine-wide motion settings."""

    kinematics: Literal["cartesian"] = "cartesian"
    max_velocity: float | None = None
    max_accel: float | None = None


@dataclass(slots=True)
class Stepper:
    """One axis stepper and its directly configured limit switch."""

    axis: str
    step_pin: str | None = None
    dir_pin: str | None = None
    enable_pin: str | None = None
    rotation_distance: float | None = None
    microsteps: int | None = None
    endstop_pin: str | None = None
    position_endstop: float | None = None
    position_max: float | None = None
    endstops: list[EndstopSwitch] = field(default_factory=list, repr=False)

    @property
    def section_name(self) -> str:
        """Return the source section name for this stepper."""

        return f"stepper_{self.axis}"


@dataclass(slots=True)
class EndstopSwitch:
    """A named secondary switch linked to its target :class:`Stepper`."""

    name: str
    stepper: Stepper
    pin: str | None = None
    position: float | None = None
    type: Literal["limit", "trigger"] = "limit"


@dataclass(slots=True)
class Extruder:
    """Extruder drive, heater, sensor, and PID settings."""

    step_pin: str | None = None
    dir_pin: str | None = None
    enable_pin: str | None = None
    microsteps: int | None = None
    rotation_distance: float | None = None
    nozzle_diameter: float | None = None
    filament_diameter: float | None = None
    heater_pin: str | None = None
    sensor_type: str | None = None
    sensor_pin: str | None = None
    control: str | None = None
    pid_Kp: float | None = None
    pid_Ki: float | None = None
    pid_Kd: float | None = None
    min_temp: float | None = None
    max_temp: float | None = None


@dataclass(slots=True)
class HeaterBed:
    """Heated-bed output, sensor, and safety limits."""

    heater_pin: str | None = None
    sensor_type: str | None = None
    sensor_pin: str | None = None
    control: str | None = None
    min_temp: float | None = None
    max_temp: float | None = None


@dataclass(slots=True)
class Spindle:
    """Spindle PWM/enable mapping and speed limit."""

    pwm_pin: str | None = None
    enable_pin: str | None = None
    max_rpm: float | None = None


@dataclass(slots=True)
class MachineConfigGraph:
    """Linked, compiler-ready representation of a machine profile."""

    printer: Printer | None = None
    steppers: dict[str, Stepper] = field(default_factory=dict)
    endstop_switches: dict[str, EndstopSwitch] = field(default_factory=dict)
    extruder: Extruder | None = None
    heater_bed: HeaterBed | None = None
    spindle: Spindle | None = None

    def find_stepper(self, target: str) -> Stepper | None:
        """Find a stepper by axis (``y``) or section name (``stepper_y``)."""

        axis = target.removeprefix("stepper_")
        return self.steppers.get(axis)


# A concise alias for consumers that prefer the domain term over graph shape.
MachineConfig = MachineConfigGraph


__all__ = [
    "EndstopSwitch",
    "Extruder",
    "HeaterBed",
    "MachineConfig",
    "MachineConfigGraph",
    "Printer",
    "Spindle",
    "Stepper",
]
