"""Klipper-side data model.

Dataclasses produced by :mod:`backend.modules.machineconfig.parser`
from a Klipper ``.cfg`` source. Every type here describes a piece of
the *input* configuration; the LinuxCNC-side mirror lives in
:mod:`.linuxcnc_models`.

Keeping the two sides in separate files makes the one-to-many
relationship between an :class:`~.linuxcnc_models.Axis` and its
list of :class:`~.linuxcnc_models.Joint` objects explicit — a
single Klipper stepper (or several) flows through one joint; the
axis is the LinuxCNC-level grouping that owns the list.
"""

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
    """One axis stepper and its directly configured limit switch.

    A Klipper profile can declare more than one :class:`Stepper` per
    axis (e.g. ``[stepper_y]`` and ``[stepper_y1]``); each lives as
    its own :class:`Stepper` keyed by section name on the parent
    :class:`MachineConfigGraph`. The downstream
    :class:`~.linuxcnc_models.AxisBuilder` decides whether multiple
    steppers on one axis become multiple joints (dual-motor Y) or
    merge into a single joint.
    """

    axis: str
    step_pin: str | None = None
    dir_pin: str | None = None
    enable_pin: str | None = None
    rotation_distance: float | None = None
    microsteps: int | None = None
    endstop_pin: str | None = None
    position_endstop: float | None = None
    position_max: float | None = None
    endstops: list["EndstopSwitch"] = field(default_factory=list, repr=False)

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
class TMC2209:
    """TMC2209 stepper driver configuration."""

    stepper: str  # linked stepper section name (e.g. "stepper_x")
    uart_pin: str | None = None
    run_current: float | None = None
    stealthchop_threshold: int | None = None
    microsteps: int | None = None
    interpolate: bool | None = None
    hold_current: float | None = None
    sense_resistor: float | None = None


@dataclass(slots=True)
class MCU:
    """MCU configuration (transport settings + hal_type)."""

    hal_type: str = "remora"  # "remora" or "parallel"


@dataclass(slots=True)
class MachineConfigGraph:
    """Linked, compiler-ready representation of a machine profile.

    This is the *input* side of the compiler pipeline. It is keyed by
    section name so multi-motor axes (e.g. ``stepper_y`` and
    ``stepper_y1``) coexist without collision; the axis/joint mapping
    happens downstream in :class:`~.linuxcnc_models.AxisBuilder`.
    """

    printer: Printer | None = None
    steppers: dict[str, Stepper] = field(default_factory=dict)
    endstop_switches: dict[str, EndstopSwitch] = field(default_factory=dict)
    extruder: Extruder | None = None
    heater_bed: HeaterBed | None = None
    spindle: Spindle | None = None
    tmc2209s: dict[str, TMC2209] = field(default_factory=dict)
    mcu: MCU | None = None

    def find_stepper(self, target: str) -> "Stepper | None":
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
    "MCU",
    "Printer",
    "Spindle",
    "Stepper",
    "TMC2209",
]