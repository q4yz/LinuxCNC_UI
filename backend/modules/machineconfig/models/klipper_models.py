"""Klipper-side data model.

Dataclasses produced by :mod:`backend.modules.machineconfig.parser`
from a Klipper ``.cfg`` source. Every type here describes a piece of the
*input* configuration; the LinuxCNC-side mirror lives in
:mod:`.linuxcnc_models`.

Keeping the two sides in separate files makes the one-to-many
relationship between an :class:`~.linuxcnc_models.Axis` and its
list of :class:`~.linuxcnc_models.Joint` objects explicit — a
single Klipper stepper (or several) flows through one joint; the
axis is the LinuxCNC-level grouping that owns the list.

Heater extraction onto ``hardware.json`` is its own concern; see
:mod:`backend.modules.machineconfig.compilers.heater_extractor`.
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
class Heater:
    """A temperature-controlled heater with sensor and (optional) PID config.

    Common base for extruders and beds. The ``name`` field is the
    canonical hardware.json heater name produced by
    :func:`backend.modules.machineconfig.compilers.heater_extractor.derive_heater_name`
    and is set by the parser, not by the section author.

    Required fields (``heater_pin``, ``sensor_pin``, ``control``)
    are still typed as optional because the parser emits them after
    validation, but missing values cause a parse error before the
    heater is constructed.
    """

    name: str = ""
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
class Extruder(Heater):
    """Extruder is-a :class:`Heater` plus a stepper + filament drive.

    Every extruder section in a Klipper config must provide the
    heater fields (``heater_pin``, ``sensor_pin``, ``control``) as
    well as the stepper fields. The parser enforces the heater
    requirement; the stepper fields remain optional because Klipper
    allows standalone extruder-like sections for some toolheads.
    """

    step_pin: str | None = None
    dir_pin: str | None = None
    enable_pin: str | None = None
    microsteps: int | None = None
    rotation_distance: float | None = None
    nozzle_diameter: float | None = None
    filament_diameter: float | None = None


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
class Fan:
    """A standalone PWM-controlled fan.

    Klipper's ``[fan]`` and ``[fan_generic]`` sections map to this
    dataclass. The ``name`` field is the canonical id derived from
    the section header (``[fan]`` -> ``"fan"``,
    ``[fan_generic part_cooling]`` -> ``"fan_generic_part_cooling"``)
    via :func:`backend.modules.machineconfig.compilers.derive_fan_name`
    and is set by the parser, not by the section author.

    Required field ``pin`` is typed as optional because the parser
    emits it after validation; missing values raise a parse error
    before the fan is constructed.

    Optional ``max_power`` (0.0–1.0) controls the ``PWM Max`` value
    in the Remora board JSON. The runtime clamps it to 1.0 and
    scales it to 8-bit (0–255) so a Klipper ``max_power: 0.5`` ends
    up as ``PWM Max: 128``.
    """

    name: str = ""
    pin: str | None = None
    max_power: float | None = None


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

    Heaters live in a single dict keyed by the canonical hardware.json
    heater name (see
    :func:`backend.modules.machineconfig.compilers.heater_extractor.derive_heater_name`).
    Extruders are stored as :class:`Extruder` instances in the same
    dict and can be retrieved by name; the ``heater`` of an extruder
    is the same object so the standard :class:`Heater` accessors work
    unchanged.
    """

    printer: Printer | None = None
    steppers: dict[str, Stepper] = field(default_factory=dict)
    endstop_switches: dict[str, EndstopSwitch] = field(default_factory=dict)
    heaters: dict[str, Heater] = field(default_factory=dict)
    spindle: Spindle | None = None
    tmc2209s: dict[str, TMC2209] = field(default_factory=dict)
    fans: dict[str, Fan] = field(default_factory=dict)
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
    "Fan",
    "Heater",
    "MachineConfig",
    "MachineConfigGraph",
    "MCU",
    "Printer",
    "Spindle",
    "Stepper",
    "TMC2209",
]
