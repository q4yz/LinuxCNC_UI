"""Klipper-side data model.

Dataclasses produced by :mod:`backend.machineconfig_parser`
from a Klipper ``.cfg`` source. Every type here describes a piece of the
*input* configuration; the LinuxCNC-side mirror lives in
:mod:`.linuxcnc_models`.

Keeping the two sides in separate files makes the one-to-many
relationship between an :class:`~.linuxcnc_models.Axis` and its
list of :class:`~.linuxcnc_models.Joint` objects explicit — a
single Klipper stepper (or several) flows through one joint; the
axis is the LinuxCNC-level grouping that owns the list.

Heater extraction onto ``hardware.json`` is its own concern; see
:mod:`backend.services.machineconfig.heater_extractor`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ConnectionType = Literal[
    "rs485",
    "vfd_rs485",
    "remora-spi",
    "remora-eth",
    "parallelport",
    "ethercat",
    "usb_arduino",
    "dummy",
]


def connection_to_hal_type(connection: ConnectionType) -> str:
    """Map a ``ConnectionType`` to the legacy ``hal_type`` discriminator.

    The HAL generator historically selected its template via a
    ``hal_type`` of ``"remora"`` or ``"parallel"``. The multi-MCU
    world uses the richer ``connection`` vocabulary; this helper
    collapses it back to the original two-value discriminator so the
    HAL generator keeps working without changes.

    * ``remora-spi`` / ``remora-eth`` -> ``"remora"``
    * ``parallelport`` / ``rs485`` / ``vfd_rs485`` / ``ethercat`` /
      ``usb_arduino`` / ``dummy`` -> ``"parallel"``
      (the legacy generator only knew "parallel"; the new
      transports land in the parallel-mode template until a
      dedicated renderer is added).
    """
    if connection in {"remora-spi", "remora-eth"}:
        return "remora"
    return "parallel"


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
    # Motor steps per revolution. Overrides the 200-step assumption in
    # AxisBuilder's SCALE formula — a 0.9deg motor is 400.
    full_steps_per_rotation: int | None = None
    endstop_pin: str | None = None
    position_endstop: float | None = None
    position_min: float | None = None
    position_max: float | None = None
    homing_speed: float | None = None
    # Class-B (Remora) position-loop tuning: `setp remora.joint.N
    # .deadband` / `.pgain`. Real reference values, not invented —
    # `machine_config/example/ender3/ender3.hal` sets `deadband` on
    # joint 2 and `pgain` on joint 3. No class-A equivalent (no such
    # loop to tune).
    deadband: float | None = None
    pgain: float | None = None
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
    :func:`backend.services.machineconfig.heater_extractor.derive_heater_name`
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
class SpindleAnalog:
    """Analog (PWM + enable) spindle.

    Carries the physical MCU pins that the config.txt generator
    turns into a Remora PWM module, plus the RPM clamp range.
    """

    pwm_pin: str | None = None
    enable_pin: str | None = None
    max_rpm: float | None = None
    min_rpm: float | None = None


@dataclass(slots=True)
class SpindleDigital:
    """Digital (RS-485 / EtherCAT / vfdmod) spindle — pins, not a protocol.

    Declares **pins** like any other component
    (`.agent/component/digital_spindle.md`); the `<mcu_id>:` prefix on
    each pin says which controller carries it (a VFD on RS-485, an
    EtherCAT drive, ...) and that MCU's router mapper is the only
    place that knows how the pin becomes real HAL. This replaced the
    earlier ``*_signal`` shape, which named already-resolved HAL
    signals directly and so could never be routed to an MCU.
    """

    max_rpm: float | None = None
    min_rpm: float | None = None
    spindle_number: int | None = None
    rpm_scale: float | None = None

    run_pin: str | None = None
    reverse_pin: str | None = None
    speed_pin: str | None = None
    speed_fb_pin: str | None = None
    at_speed_pin: str | None = None
    fault_pin: str | None = None
    is_connected_pin: str | None = None
    error_count_pin: str | None = None


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
    via :func:`backend.services.machineconfig.derive_fan_name`
    and is set by the parser, not by the section author.

    Required field ``pin`` is typed as optional because the parser
    emits it after validation; missing values raise a parse error
    before the fan is constructed.

    Optional ``max_power`` (0.0–1.0) controls the ``PWM Max`` value
    in the Remora board JSON. The runtime clamps it to 1.0 and
    scales it to 8-bit (0–255) so a Klipper ``max_power: 0.5`` ends
    up as ``PWM Max: 128``.

    ``shutdown_speed`` (0.0–1.0) is Klipper's own "duty on estop/
    shutdown" field — ingested as data today; not yet wired into a
    HAL safety circuit (`.agent/component/fan.md`).
    """

    name: str = ""
    pin: str | None = None
    max_power: float | None = None
    shutdown_speed: float | None = None


@dataclass(slots=True)
class HeaterFan:
    """A fan the HAL manages automatically off a heater's own reading —
    never operator/G-code commandable (`.agent/component/fan.md` §
    "kind: heater"). Klipper's real ``[heater_fan <name>]`` section;
    distinct from a heater's own optional ``fan:`` reference (a plain
    passthrough SP channel the operator drives).

    ``heater`` is the *raw* Klipper heater section name (e.g.
    ``"extruder"``, Klipper's own default when omitted) — resolving
    it to this compiler's canonical tool id (``"heater_extruder"``)
    is `hardware_json_generator`'s job, the same layer that resolves
    every other cross-reference.
    """

    name: str = ""
    pin: str | None = None
    max_power: float | None = None
    shutdown_speed: float | None = None
    heater: str = "extruder"
    heater_temp: float | None = None
    fan_speed: float | None = None


@dataclass(slots=True)
class Estop:
    """The machine's single E-stop component (`.agent/component/estop.md`).

    Both fields are optional pins, like every other component — an
    empty ``[estop]`` block is valid on its own (the UI's own
    ``webgui.estop`` signal reaches ``halui.estop.activate`` through a
    plain passthrough net — ``StateService.activate_estop()`` now
    generates the pulse itself, see ``EstopWebguiMapper``), regardless
    of hardware. ``fault_pin`` is a physical E-stop loop's fault input;
    ``out_pin`` mirrors LinuxCNC's own enable state out to a physical
    pin (a lamp, a relay, ...). Independently optional — declaring
    one does not require the other.
    """

    fault_pin: str | None = None
    out_pin: str | None = None


@dataclass(slots=True)
class MCU:
    """One MCU configuration (transport settings + optional identity).

    A Klipper profile may declare any number of ``[mcu]`` /
    ``[mcu NAME]`` sections; each one becomes an :class:`MCU`
    record on :attr:`MachineConfigGraph.mcus`. The fields mirror
    the source keywords:

    * ``connection`` — the transport type. The single source of
      truth for MCU behaviour: the capability class and the HAL
      router both branch on it (a derived ``is_remora`` boolean was
      removed — it couldn't scale past two transport families).
      Defaults to ``"remora-spi"`` for back-compat with the
      historical single-MCU flow.
    * ``interface`` — a free-form transport selector (e.g. a
      ``/dev/serial/by-id/...`` path for RS-485). Optional.
    * ``board`` — the operator-visible board name (e.g.
      ``"BIGTREETECH OCTOPUS"``). Optional and **never autofilled**:
      HAL generation cares about protocols and device paths, not PCB
      names — the firmware-side config generator surfaces it only
      when the profile actually declares it.
    * ``baud_rate`` / ``node_id`` / ``parity`` — the Modbus serial
      trio, only valid on ``vfd_rs485`` (or legacy ``rs485``)
      sections. ``parity`` is normalised to ``none``/``even``/
      ``odd``; all three stay ``None`` when undeclared so the
      router applies its documented defaults (9600 / 1 / none).
    * ``reset_pin`` — the board's own reset GPIO, only valid on
      ``remora-spi``/``remora-eth``. Real, not invented: every module
      in the reference firmware config
      (`machine_config/example/ender3/config.txt`) is preceded by a
      `"Reset Pin"` module; this is a physical pin string like any
      other (`.agent/component/README.md` § 1 grammar), formatted at
      emission time the same way a joint's `step_pin` is.

    The ``hal_type`` property collapses :attr:`connection` to
    the legacy two-value discriminator the original HAL generator
    consumed (it remains the only transport ever loaded by the
    generated HALFILE).
    """

    connection: ConnectionType = "remora-spi"
    interface: str | None = None
    board: str | None = None
    baud_rate: int | None = None
    node_id: int | None = None
    parity: str | None = None
    reset_pin: str | None = None

    @property
    def hal_type(self) -> str:
        """Legacy discriminator the HAL generator consumes."""
        return connection_to_hal_type(self.connection)


@dataclass(slots=True)
class MachineConfigGraph:
    """Linked, compiler-ready representation of a machine profile.

    This is the *input* side of the compiler pipeline. It is keyed by
    section name so multi-motor axes (e.g. ``stepper_y`` and
    ``stepper_y1``) coexist without collision; the axis/joint mapping
    happens downstream in :class:`~.linuxcnc_models.AxisBuilder`.

    Heaters live in a single dict keyed by the canonical hardware.json
    heater name (see
    :func:`backend.services.machineconfig.heater_extractor.derive_heater_name`).
    Extruders are stored as :class:`Extruder` instances in the same
    dict and can be retrieved by name; the ``heater`` of an extruder
    is the same object so the standard :class:`Heater` accessors work
    unchanged.
    """

    printer: Printer | None = None
    # The machine's single E-stop component. ``None`` until parsed;
    # ``hardware_json_generator.build_hardware_json`` is where "exactly
    # one [estop] is required" is actually enforced (not here — see
    # that module's docstring for why the boundary sits there and not
    # in the section-by-section parser).
    estop: Estop | None = None
    steppers: dict[str, Stepper] = field(default_factory=dict)
    endstop_switches: dict[str, EndstopSwitch] = field(default_factory=dict)
    heaters: dict[str, Heater] = field(default_factory=dict)
    spindle_analog: SpindleAnalog | None = None
    # Multiple digital spindles keyed by canonical id
    # (``spindle_digital`` for the bare form,
    # ``spindle_digital_test`` for ``[spindle test]``, ...).
    # Single-spindle callers should prefer the ``spindle_digital``
    # deprecated property below — it returns the first declared
    # record and preserves the historical ``| None`` shape.
    spindle_digitals: dict[str, SpindleDigital] = field(default_factory=dict)
    tmc2209s: dict[str, TMC2209] = field(default_factory=dict)
    fans: dict[str, Fan] = field(default_factory=dict)
    heater_fans: dict[str, HeaterFan] = field(default_factory=dict)
    # Multiple MCUs. The key is the section's object name
    # (``"mcu"`` for the bare ``[mcu]`` form, ``"a"`` for ``[mcu a]``).
    mcus: dict[str, MCU] = field(default_factory=dict)
    # ``[duplicate_pin_override]``'s ``pins:`` list, normalised to
    # ``"<mcu_id>:<pin_id>"`` (modifiers stripped — a collision is a
    # property of the raw physical pin, not of how one caller happens
    # to invert it). An operator-declared exception to the pin-conflict
    # guard; see `.agent/component/README.md` § 3.
    duplicate_pin_overrides: frozenset[str] = field(default_factory=frozenset)

    @property
    def mcu(self) -> MCU | None:
        """Back-compat accessor returning the first declared MCU.

        Historical callers (HAL generator, hardware.json emitter)
        read ``graph.mcu`` to learn the active transport. The
        multi-MCU world uses :attr:`mcus` for the full inventory;
        this property keeps the legacy single-MCU API alive while
        the rest of the codebase migrates.
        """
        for value in self.mcus.values():
            return value
        return None

    @property
    def spindle_digital(self) -> SpindleDigital | None:
        """Back-compat accessor returning the first declared digital spindle.

        Historical callers read ``graph.spindle_digital`` to learn the
        single spindle's HAL signal map. The multi-instance world uses
        :attr:`spindle_digitals` for the full inventory; this property
        keeps the legacy single-spindle API alive while the rest of
        the codebase migrates. Returns the first declared record (in
        dict insertion order) so a profile with one bare ``[spindle]``
        behaves identically to before.
        """
        for value in self.spindle_digitals.values():
            return value
        return None

    def find_stepper(self, target: str) -> "Stepper | None":
        """Find a stepper by axis (``y``) or section name (``stepper_y``)."""

        axis = target.removeprefix("stepper_")
        return self.steppers.get(axis)


# A concise alias for consumers that prefer the domain term over graph shape.
MachineConfig = MachineConfigGraph


__all__ = [
    "ConnectionType",
    "EndstopSwitch",
    "Estop",
    "Extruder",
    "Fan",
    "Heater",
    "HeaterFan",
    "MachineConfig",
    "MachineConfigGraph",
    "MCU",
    "Printer",
    "SpindleAnalog",
    "SpindleDigital",
    "Stepper",
    "TMC2209",
    "connection_to_hal_type",
]
