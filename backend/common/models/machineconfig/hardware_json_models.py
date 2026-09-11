"""Pydantic models for the canonical ``hardware.json`` v2 shape.

The ``hardware.json`` payload is the machine's hardware contract —
emitted by the Klipper compiler, consumed by the runtime (the
temperature module seeds its sensors from ``temperature_sensors``,
the jog watchdog reads the endstop records, the ToolPanel reads
the ``tools`` list, etc.).

Versioning
----------
The top-level model is pinned to ``version: "2.1"`` so the
consumer can branch on the shape without guessing. The shape is
flat with explicit ``id`` fields so every cross-reference is a
string handle — the cross-reference validator walks the graph in
one pass and rejects any unresolved link.

Naming convention
-----------------
Entity list names are the type discriminator. ``temperature_sensors``
and ``fans`` stay as separate top-level lists because they can exist
without an associated tool (CPU temp sensors, standalone cooling
fans). ``tools`` is the operator-facing list — every entity the
operator can command from the dashboard — and it absorbs what used
to be the ``heaters`` list. ``extruder`` and ``heated_bed`` both
land in ``tools`` with a ``type`` discriminator; spindle variants
land there too. A future ``laser`` type is reserved on the schema
literal but no current compiler emits it.

Cross-references inside a tool entry resolve into the matching
top-level list — ``tool.sensor`` into ``temperature_sensors[].id``,
``tool.fan`` into ``fans[].id``. The parent list is the type
discriminator; a spindle tool's ``pwm_pin`` does NOT resolve into
``fans`` even when a fan happens to share the pin.

Axis identification
-------------------
An axis is identified by a string ``id`` (the canonical LinuxCNC
letter — ``x``, ``y``, ``z``, ``a``, ...) and lists its constituent
joints as ``joint_numbers: list[int]``. ``joints`` are the motors
(physical steppers) — they keep their own ``joint_number`` integer
that maps to a Remora stepgen channel ``remora.joint.{N}.*``. An
axis owns one or more joints; a multi-motor axis (e.g. dual-motor
Y) lists every driving joint in ``joint_numbers``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


#: Connection types accepted on an MCU section. Mirrors
#: :data:`machineconfig_schema.ALLOWED_CONNECTION_TYPES`
#: so the hardware.json consumer can branch on the same vocabulary
#: the parser enforces.
HARDWARE_MCU_CONNECTION_TYPES = frozenset(
    {
        "vfd_rs485",
        "rs485",
        "remora-spi",
        "remora-eth",
        "parallelport",
        "ethercat",
        "usb_arduino",
        "dummy",
    }
)


# ---------------------------------------------------------------------- #
# Entity models                                                           #
# ---------------------------------------------------------------------- #


class Axis(BaseModel):
    """A kinematic axis. Owns the joints that drive it plus an
    optional endstop switch.

    An axis is wired to a switch via exactly one of two fields:

    * ``endstop`` — a string id reference into the top-level
      ``endstops[]`` array. The switch is a first-class entity
      shared with any other axis that also references the same id
      (one physical switch can serve multiple axes).
    * ``endstop_pin`` — an inline pin string, mirroring Klipper's
      ``endstop_pin:`` syntax. Provided for input compatibility with
      hand-edited ``hardware.json`` files; the compiler always
      converts this form into a top-level ``Endstop`` entity plus
      an ``endstop`` reference before emitting.

    ``position_endstop`` carries the axis position at which the
    switch fires (Klipper's ``position_endstop``); the runtime
    uses it during homing. ``position_max`` carries the axis
    travel limit (Klipper's ``position_max``). Both fields are
    axis-level because they describe motion in the axis
    coordinate frame, not per-motor scaling; multiple joints on
    one axis share the same values. ``endstop`` and ``endstop_pin``
    remain mutually exclusive — the model rejects a payload that
    sets both.

    Identification
    --------------
    An axis is identified by a string ``id`` (the canonical LinuxCNC
    letter — ``x``, ``y``, ``z``, ``a``, ...) and lists its
    constituent joints as ``joint_numbers: list[int]``. An empty
    ``joint_numbers`` list is allowed (axis with no joints at all);
    the cross-ref validator walks the list and finds nothing to
    resolve, which is the correct outcome.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    joint_numbers: list[int] = Field(default_factory=list)
    endstop: str | None = None
    endstop_pin: str | None = None
    position_min: float | None = None
    position_max: float | None = None
    position_endstop: float | None = None

    @model_validator(mode="after")
    def _validate_endstop_exclusive(self) -> "Axis":
        if self.endstop is not None and self.endstop_pin is not None:
            raise ValueError(
                f"Axis (id={self.id}) sets both "
                f"'endstop' and 'endstop_pin'; only one may be set."
            )
        return self


class Stepper(BaseModel):
    """One physical stepper drive. References its driver and pins.

    The pin fields are :data:`Optional` because the parser's
    :class:`Stepper` dataclass makes them optional — they are
    ``None`` when the user's Klipper config doesn't declare them.
    The model keeps the constraint "no extra fields" so the
    consumer can trust every field name, but doesn't reject
    partial configs (a separate ticket will surface the missing
    fields as a runtime error).

    Motion-envelope fields (``position_min``, ``position_max``,
    ``position_endstop``) live on :class:`Axis` — they describe
    travel in the axis coordinate frame, not per-motor scaling —
    so this record only carries the per-motor scaling/identity:
    ``joint_number`` (the LinuxCNC ``[JOINT_N]`` index), the
    driver reference, the three pin fields, ``microsteps``,
    ``rotation_distance``, and the optional ``homing_speed``.

    ``joint_number`` mirrors the LinuxCNC-side ``Joint.joint_number``
    (the index in the per-axis ``joints`` list, then across
    canonical axis letters X / Y / Z / A / ...). The number is
    stable across re-orderings of the source Klipper config — the
    generator walks the canonical axis letter order, not the
    source-declaration order — so the runtime can map a wire
    ``joint_number`` to a Remora stepgen channel
    (``remora.joint.{N}.scale`` etc.) deterministically.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    joint_number: int = Field(ge=0)
    driver: str | None = None
    step_pin: str | None = None
    dir_pin: str | None = None
    enable_pin: str | None = None
    microsteps: int | None = None
    rotation_distance: float | None = None
    # Motor steps per revolution (200 for a 1.8deg motor, 400 for a
    # 0.9deg one). Carried so the SCALE formula is reproducible from
    # this file alone instead of assuming the 200-step default.
    full_steps_per_rotation: int | None = None
    homing_speed: float | None = None
    # Class-B (Remora) position-loop tuning — `setp remora.joint.N
    # .deadband` / `.pgain`. No class-A equivalent (no such loop to
    # tune); real values from the reference config, not invented
    # (`machine_config/example/ender3/ender3.hal`: `deadband` on
    # joint 2, `pgain` on joint 3).
    deadband: float | None = None
    pgain: float | None = None


class Driver(BaseModel):
    """A stepper driver chip (TMC2209, etc.)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: str
    uart_pin: str | None = None
    run_current: float | None = None
    microsteps: int | None = None
    stealthchop_threshold: int | None = None
    interpolate: bool | None = None
    hold_current: float | None = None
    sense_resistor: float | None = None


class Endstop(BaseModel):
    """A single physical endstop switch.

    Mirrors the Klipper source: just an id and a pin. The schema
    deliberately strips the previous ``type``, ``pos``, and
    ``stepper`` back-reference fields — the axis that hosts the
    switch already carries its position (``Axis.position_endstop``)
    and the behavioural tag is implicit from context (switches
    referenced by an axis are part of that axis's homing
    sequence).

    One ``Endstop`` can be referenced by multiple axes; the
    cross-reference validator walks every ``Axis.endstop`` to
    ensure the id resolves into this list, but it does not
    constrain how many axes may share the record.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    pin: str


class TemperatureSensor(BaseModel):
    """A single temperature sensor (thermistor, RTD, etc.).

    Lives in the ``temperature_sensors`` top-level list. The list
    name is the type discriminator — when pressure and flow sensors
    land later, they will live in their own lists and not share
    ids with this one.

    The list is intentionally separate from ``tools`` because
    temperature sensors can exist without an associated heater
    (CPU temp gauges, board-mounted RTDs) and need to surface on
    the chart regardless of whether anything heats them.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    pin: str
    type: str | None = None


class Fan(BaseModel):
    """A single output fan — either operator/G-code commandable
    (``kind: "part"``, Klipper's ``[fan]``/``[fan_generic ...]``) or
    HAL-managed off a heater's own reading (``kind: "heater"``,
    Klipper's ``[heater_fan <name>]``) — never both
    (`.agent/component/fan.md`).

    ``max_power`` (0.0–1.0) is the PWM duty-cycle ceiling. The
    Remora board JSON uses an 8-bit ``pwm_max`` field; the
    runtime scales ``max_power`` to 0–255 before pushing the value into the
    firmware. Persisting the float here keeps the round-trip
    deterministic (no need to re-read ``config.txt`` to recover the
    duty-cycle cap). ``shutdown_speed`` is Klipper's own "duty on
    estop/shutdown" field — carried as data; not yet wired into a HAL
    safety circuit.

    The list is intentionally separate from ``tools`` because a
    standalone ``[fan]`` section (part cooling) does not need an
    operator-facing card in the ToolPanel — it just needs an
    addressable record so the temperature module can wire a fan
    onto a heater.

    ``heater``/``heater_temp``/``fan_speed`` are ``kind: "heater"``
    only: ``heater`` resolves into ``tools[].id`` (the heater this
    fan follows), ``heater_temp`` is the reading (°C) that turns it
    on, ``fan_speed`` the 0.0-1.0 speed it runs at once triggered.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    pin: str
    kind: Literal["part", "heater"] = "part"
    max_power: float | None = None
    shutdown_speed: float | None = None
    # ---- kind: "heater" only ---------------------------------------- #
    heater: str | None = None
    heater_temp: float | None = None
    fan_speed: float | None = None


class Estop(BaseModel):
    """The machine's single E-stop component (`.agent/component/estop.md`).

    Both fields are optional — an empty ``estop`` object (``{}`` on
    the wire, both fields dropped by ``exclude_none``) is valid and
    is exactly what a UI-only machine emits: the operator's
    `webgui.estop` signal always reaches `halui.estop.activate`
    through a `oneshot` pulse regardless of hardware.
    :func:`build_hardware_json` is what actually enforces "exactly
    one ``[estop]``" on the source ``.cfg`` — this model stays
    ``Optional`` on :class:`HardwareJson` so a hand-crafted or
    pre-existing payload (this compiler's own test fixtures included)
    that never declared one still validates.
    """

    model_config = ConfigDict(extra="forbid")

    fault_pin: str | None = None
    out_pin: str | None = None


class McuInfo(BaseModel):
    """A single MCU record exposed in ``hardware.json``.

    The list is a transparency surface — consumers querying the
    hardware contract can see what ``[mcu]`` / ``[mcu NAME]``
    sections the source profile declared, the transport each one
    targets, and any operator-set board name. The runtime does NOT
    branch on this list (the existing single-remora assumption still
    holds); the field exists so the editor / dashboard can render
    the multi-MCU story the moment the multi-board future lands.

    ``id`` is the section header's object name (``"mcu"`` for the
    bare ``[mcu]`` form, ``"a"`` for ``[mcu a]``); it doubles as a
    pin-qualifier prefix in the source syntax.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    connection: Literal[
        "vfd_rs485",
        "rs485",
        "remora-spi",
        "remora-eth",
        "parallelport",
        "ethercat",
        "usb_arduino",
        "dummy",
    ]
    interface: str | None = None
    board: str | None = None
    # Modbus serial settings — present only on vfd_rs485/rs485 MCUs
    # that declared them. The vfdmod router applies the documented
    # defaults (9600 / 1 / none) when these are absent.
    baud_rate: int | None = None
    node_id: int | None = None
    parity: Literal["none", "even", "odd"] | None = None
    # The board's own reset GPIO — present only on remora-spi/
    # remora-eth MCUs that declared one. Real firmware field, not
    # invented: see `.agent/component/mcu_spi_remora.md`.
    reset_pin: str | None = None


# ---------------------------------------------------------------------- #
# Tools                                                                   #
# ---------------------------------------------------------------------- #


# The tool type literal is the runtime discriminator. Each value
# maps to a specific operator-facing card in the frontend's
# ToolPanel:
#
# * ``extruder``        — heat + motion (heater + stepper + filament).
# * ``spindle_digital`` — VFD driven by live net signals; RPM feedback.
# * ``spindle_analog``  — VFD driven by 0–10 V PWM; no RPM feedback.
# * ``heated_bed``      — heat only (heater + sensor).
# * ``laser``           — reserved for a future laser driver; no
#                          compiler emits it yet.
ToolType = Literal[
    "extruder", "spindle_digital", "spindle_analog", "heated_bed", "laser"
]


class Tool(BaseModel):
    """An operator-facing tool — anything the dashboard can command.

    Replaces the v2 ``heaters`` list. ``extruder`` and ``heated_bed``
    entries fold in the fields the old ``Heater`` record carried
    (``heater_pin``, ``control``, ``min_temp``, ``max_temp``) plus
    string references into the separate ``temperature_sensors`` and
    ``fans`` lists. ``spindle_digital`` and ``spindle_analog``
    entries carry their own HAL-facing pin fields (``run_pin`` etc.
    for the digital path, ``pwm_pin`` / ``enable_pin`` for the analog
    path) plus the shared ``min_rpm`` / ``max_rpm`` clamps.

    The ``name`` field is the operator-facing label (chip text in
    the ToolPanel header). ``id`` is the canonical machine handle
    — same namespace policy as every other top-level list.

    Cross-references resolve into the matching top-level list by
    parent-list discriminator — ``sensor`` into
    ``temperature_sensors[].id``, ``fan`` into ``fans[].id``. No
    cross-reference exists for the spindle HAL pins — a digital
    spindle's pins (``run_pin`` etc.) are ``[modifiers][mcu:]pin``
    strings the HAL compiler routes, exactly like a stepper's
    ``step_pin`` (`.agent/component/README.md` § 1), not ids into
    another list.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str | None = None
    type: ToolType

    # ---- SpindleDigital shared (digital + analog) ------------------------ #
    min_rpm: float | None = None
    max_rpm: float | None = None

    # ---- SpindleDigital analog only --------------------------------------- #
    pwm_pin: str | None = None
    enable_pin: str | None = None

    # ---- SpindleDigital digital only -------------------------------------- #
    # Pins, not a protocol (`.agent/component/digital_spindle.md`):
    # the `<mcu_id>:` prefix on each pin says which controller (a VFD
    # on RS-485, an EtherCAT drive, ...) carries it. The runtime never
    # reads these — ``SpindleDigitalMapper`` addresses the tool by a
    # fixed HAL naming convention off its ``id`` suffix instead; these
    # exist purely as routing data for the HAL compiler.
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

    # ---- Heating (extruder + heated_bed) --------------------------- #
    # ``sensor`` resolves into ``temperature_sensors[].id``;
    # ``fan`` resolves into ``fans[].id``. Both are optional —
    # a profile that declares a heater without a sensor / fan is
    # still valid hardware.json; the ToolPanel just renders no
    # feedback tiles for it.
    sensor: str | None = None
    heater_pin: str | None = None
    fan: str | None = None
    control: str | None = None
    min_temp: float | None = None
    max_temp: float | None = None

    # PID gains for ``control: "pid"``. Carried for the HAL compiler,
    # which emits them as the loop's INI section
    # (``[EXT0] PID_KP`` etc. — see .agent/component/heater.md). The UI
    # never shows them; they are here so no information is lost between
    # the source .cfg and this file.
    pid_kp: float | None = None
    pid_ki: float | None = None
    pid_kd: float | None = None

    # ---- Extruder-only, informational ------------------------------ #
    filament_diameter: float | None = None
    nozzle_diameter: float | None = None


# ---------------------------------------------------------------------- #
# Root model                                                              #
# ---------------------------------------------------------------------- #


class HardwareJson(BaseModel):
    """The canonical ``hardware.json`` v2 root model.

    The ``version`` field is the contract surface: changing the
    numeric major (or any breaking field shape) requires a new
    version. The cross-reference validator runs once after the
    model is constructed to enforce every ``*_id``-style reference
    resolves into the right list.

    The ``heaters`` list was folded into ``tools`` in this revision
    — every former heater is now a ``Tool`` entry with
    ``type="extruder"`` or ``type="heated_bed"``. ``temperature_sensors``
    and ``fans`` remain separate top-level lists so sensors / fans
    that are not bound to a tool can still appear.
    """

    model_config = ConfigDict(extra="forbid")

    # "2.1" stays accepted so machines generated before the
    # losslessness pass still validate; new output is tagged "2.2".
    version: Literal["2.1", "2.2"] = "2.2"
    machine: str
    source: str
    kinematics: str
    hal_type: str

    # Machine-wide motion envelope from the profile's ``[printer]``
    # section. Feeds ``[TRAJ] MAX_LINEAR_VELOCITY`` /
    # ``MAX_LINEAR_ACCELERATION``; previously parsed and discarded.
    max_velocity: float | None = None
    max_accel: float | None = None

    # The machine's single E-stop component. ``None`` only for a
    # payload built before this field existed (or a hand-crafted test
    # fixture) — every payload ``build_hardware_json`` emits carries
    # one, even if both pins are unset. See :class:`Estop`.
    estop: "Estop | None" = None

    axes: list[Axis] = Field(default_factory=list)
    joints: list[Stepper] = Field(default_factory=list)
    drivers: list[Driver] = Field(default_factory=list)
    endstops: list[Endstop] = Field(default_factory=list)
    # ``tools`` replaces the old ``heaters`` list. The cross-reference
    # validator enforces ``tool.sensor`` and ``tool.fan`` resolve
    # into ``temperature_sensors[].id`` / ``fans[].id`` respectively.
    tools: list[Tool] = Field(default_factory=list)
    temperature_sensors: list[TemperatureSensor] = Field(default_factory=list)
    fans: list[Fan] = Field(default_factory=list)
    # Multi-MCU inventory declared by the source profile. Optional
    # on the wire for back-compat with v2 consumers that didn't have
    # multi-MCU support; new emitters always populate it. Field is
    # additive (no cross-reference resolution needed) and stays
    # inside the v2 envelope.
    mcus: list["McuInfo"] = Field(default_factory=list)
    # ``[duplicate_pin_override]``'s allowlist, normalised to
    # ``"<mcu_id>:<pin_id>"`` strings — an operator-declared exception
    # to the HAL compiler's pin-conflict guard (`.agent/component/
    # README.md` § 3). Empty for a profile that declares none.
    duplicate_pin_overrides: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_references(self) -> "HardwareJson":
        """Enforce every reference resolves into the right list.

        The check is run after the model is constructed so the
        per-field validators (id pattern, enums, etc.) have already
        failed-fast on the obvious problems. What's left is the
        graph-level consistency.
        """
        errors: list[str] = []

        # IDs are unique within each top-level list, including ``axes``
        # (axis ids are canonical LinuxCNC letters: ``x``, ``y``,
        # ``z``, ``a``, ...).
        for list_attr in (
            "axes",
            "joints",
            "drivers",
            "endstops",
            "tools",
            "temperature_sensors",
            "fans",
        ):
            self._check_unique_ids(list_attr, errors)

        # Reference lookup tables — ``{id: index}`` for fast checks.
        # ``joint_numbers_idx`` is the integer-keyed counterpart used
        # by the axis ``joint_numbers`` cross-reference check below.
        drivers_idx = {d.id: i for i, d in enumerate(self.drivers)}
        sensors_idx = {
            s.id: i for i, s in enumerate(self.temperature_sensors)
        }
        fans_idx = {f.id: i for i, f in enumerate(self.fans)}
        tools_idx = {t.id: i for i, t in enumerate(self.tools)}
        endstops_idx = {e.id: i for i, e in enumerate(self.endstops)}
        joint_numbers_idx = {
            j.joint_number: j.id for j in self.joints
        }

        # Every axis.joint_numbers[i] must exist in joints[] as a
        # joint_number; every ``axis.endstop`` must resolve into the
        # top-level ``endstops[]`` list. ``axis.endstop_pin`` is a
        # free-form pin string and does NOT require a matching
        # record (it is the inline Klipper form). Mutual exclusion
        # between ``endstop`` and ``endstop_pin`` lives on
        # :meth:`Axis._validate_endstop_exclusive`.
        for axis in self.axes:
            for jn in axis.joint_numbers:
                if jn not in joint_numbers_idx:
                    errors.append(
                        f"Axis (id={axis.id}) "
                        f"references unknown joint_number '{jn}'."
                    )
            if axis.endstop is not None and axis.endstop not in endstops_idx:
                errors.append(
                    f"Axis (id={axis.id}) references "
                    f"unknown endstop '{axis.endstop}'."
                )

        # Every joint.driver must exist in drivers[]. Synthesised
        # extruder joints have ``driver: None`` because the extruder
        # lives on the same driver chips as the Cartesian steppers
        # and the ``drivers[]`` list only enumerates motor-driver
        # chips — the extruder's stepgen is wired from
        # ``joint.step_pin`` directly.
        for joint in self.joints:
            if joint.driver is None:
                continue
            if joint.driver not in drivers_idx:
                errors.append(
                    f"Joint '{joint.id}' references unknown driver "
                    f"'{joint.driver}'."
                )

        # ``joint_number`` must be unique across the ``joints`` list —
        # the runtime maps the number to a Remora stepgen channel
        # (``remora.joint.{N}.*``), so two joints sharing a number
        # would collide at runtime.
        seen_joint_numbers: dict[int, str] = {}
        for joint in self.joints:
            other = seen_joint_numbers.get(joint.joint_number)
            if other is not None:
                errors.append(
                    f"Duplicate joint_number '{joint.joint_number}' "
                    f"on joints '{other}' and '{joint.id}'."
                )
            else:
                seen_joint_numbers[joint.joint_number] = joint.id

        # v2.1's per-axis primary ``joint_number`` uniqueness is
        # dropped here — axis identity is now the string ``id`` and
        # ``_check_unique_ids`` above already rejected duplicates
        # on that field. The runtime still enforces joint-number
        # uniqueness across ``joints[]`` for the Remora stepgen
        # mapping (see ``seen_joint_numbers`` below).

        # Every tool.sensor must exist in temperature_sensors[].
        # A pressure sensor is not a temperature sensor even if the
        # pin matches — the parent list is the type discriminator.
        # Similarly, ``tool.fan`` must exist in fans[].
        for tool in self.tools:
            if tool.sensor is not None and tool.sensor not in sensors_idx:
                errors.append(
                    f"Tool '{tool.id}' references unknown temperature "
                    f"sensor '{tool.sensor}'."
                )
            if tool.fan is not None and tool.fan not in fans_idx:
                errors.append(
                    f"Tool '{tool.id}' references unknown fan "
                    f"'{tool.fan}'."
                )

        # A ``kind: "heater"`` fan's ``heater`` must resolve into
        # ``tools[]`` — the HAL chain reads that heater's own sensor,
        # so an unresolved reference means nothing to gate on.
        for fan in self.fans:
            if fan.heater is not None and fan.heater not in tools_idx:
                errors.append(
                    f"Fan '{fan.id}' references unknown heater "
                    f"'{fan.heater}'."
                )

        if errors:
            # Raise as a single ValueError so the consumer gets the
            # full list in one shot instead of fixing them one at a time.
            raise ValueError(
                "hardware.json reference validation failed:\n  - "
                + "\n  - ".join(errors)
            )
        return self

    def _check_unique_ids(self, list_attr: str, errors: list[str]) -> None:
        seen: dict[str, int] = {}
        for i, entity in enumerate(getattr(self, list_attr)):
            eid = entity.id
            if eid in seen:
                errors.append(
                    f"Duplicate id '{eid}' in {list_attr} "
                    f"(indices {seen[eid]} and {i})."
                )
            else:
                seen[eid] = i


# ---------------------------------------------------------------------- #
# Round-trip helpers                                                       #
# ---------------------------------------------------------------------- #


def model_validate(data: Any) -> HardwareJson:
    """Validate ``data`` against :class:`HardwareJson` and return the model.

    Thin wrapper so callers don't need to import the class
    directly. The cross-reference validator runs as part of the
    standard Pydantic validation cycle.
    """

    return HardwareJson.model_validate(data)


def to_dict(model: HardwareJson) -> dict[str, Any]:
    """Serialise the model to a JSON-compatible dict."""

    return model.model_dump(mode="json", exclude_none=True)


# Forward-reference resolution safety net.
#
# ``HardwareJson.mcus`` is declared with the string annotation
# ``list["McuInfo"]`` (because ``from __future__ import annotations``
# is in effect at the top of this module). Pydantic v2 normally
# resolves forward refs lazily on first use — which works for
# :meth:`model_validate` and :meth:`model_dump` — but FastAPI's
# OpenAPI generator walks the model graph via
# :func:`model_json_schema`, a slightly different code path that has
# historically left unresolved forward refs as opaque ``Any`` entries
# (or, with older Pydantic builds, raised a cryptic lookup error).
#
# Calling :meth:`model_rebuild` here after every referenced class
# is defined forces the resolution now, against the module's
# :data:`globals`, so the OpenAPI generator sees a fully-resolved
# schema even when nothing else in the package has been imported
# yet at the moment FastAPI's app constructor wires its routes.
# The call is idempotent under Pydantic v2.
HardwareJson.model_rebuild(force=True)


__all__ = [
    "Axis",
    "Driver",
    "Endstop",
    "Estop",
    "Fan",
    "HardwareJson",
    "McuInfo",
    "Stepper",
    "TemperatureSensor",
    "Tool",
    "ToolType",
    "model_validate",
    "to_dict",
]