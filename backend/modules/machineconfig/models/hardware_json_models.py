"""Pydantic models for the canonical ``hardware.json`` v2 shape.

The ``hardware.json`` payload is the machine's hardware contract —
emitted by the Klipper compiler, consumed by the runtime (the
temperature module seeds its sensors from ``temperature_sensors``,
the jog watchdog reads the endstop records, the ToolPanel reads
the ``tools`` list, etc.).

Versioning
----------
The top-level model is pinned to ``version: "2.0"`` so the
consumer can branch on the shape without guessing. The shape is
flat with explicit ``id`` fields so every reference is a string
handle — the cross-reference validator walks the graph in one
pass and rejects any unresolved link.

Naming convention
-----------------
Entity list names are the type discriminator. ``temperature_sensors``
and ``fans`` stay as separate top-level lists because they can exist
without an associated tool (CPU temp sensors, standalone cooling
fans). ``tools`` is the new operator-facing list — every entity the
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
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


#: Connection types accepted on an MCU section. Mirrors
#: :data:`modules.machineconfig.schema.ALLOWED_CONNECTION_TYPES`
#: so the hardware.json consumer can branch on the same vocabulary
#: the parser enforces.
HARDWARE_MCU_CONNECTION_TYPES = frozenset(
    {"rs485", "remora-spi", "remora-eth", "parallelport", "dummy"}
)


# ---------------------------------------------------------------------- #
# Entity models                                                           #
# ---------------------------------------------------------------------- #


class Axis(BaseModel):
    """A kinematic axis. Owns the steppers that drive it plus an
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

    ``pos`` carries the axis position at which the switch fires
    (Klipper's ``position_endstop``); the runtime uses it during
    homing. Both forms are mutually exclusive — the model rejects
    a payload that sets both.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    steppers: list[str]
    endstop: str | None = None
    endstop_pin: str | None = None
    pos: float | None = None

    @model_validator(mode="after")
    def _validate_endstop_exclusive(self) -> "Axis":
        if self.endstop is not None and self.endstop_pin is not None:
            raise ValueError(
                f"Axis '{self.id}' sets both 'endstop' and 'endstop_pin'; "
                f"only one may be set."
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
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    driver: str | None = None
    step_pin: str | None = None
    dir_pin: str | None = None
    enable_pin: str | None = None
    microsteps: int | None = None
    rotation_distance: float | None = None
    position_min: float | None = None
    position_max: float | None = None
    position_endstop: float | None = None
    homing_speed: float | None = None


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
    switch already carries its position (``Axis.pos``) and the
    behavioural tag is implicit from context (switches referenced
    by an axis are part of that axis's homing sequence).

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
    """A single output fan.

    ``max_power`` (0.0–1.0) is the PWM duty-cycle ceiling. The
    Remora board JSON uses an 8-bit ``pwm_max`` field; the
    runtime scales ``max_power`` to 0–255 before pushing the value into the
    firmware. Persisting the float here keeps the round-trip
    deterministic (no need to re-read ``config.txt`` to recover the
    duty-cycle cap).

    The list is intentionally separate from ``tools`` because a
    standalone ``[fan]`` section (part cooling) does not need an
    operator-facing card in the ToolPanel — it just needs an
    addressable record so the temperature module can wire a fan
    onto a heater.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    pin: str
    max_power: float | None = None


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
        "rs485", "remora-spi", "remora-eth", "parallelport", "dummy"
    ]
    interface: str | None = None
    board: str | None = None
    # True for MCUs that the Remora board firmware addresses
    # (``remora-spi`` / ``remora-eth``). Computed at payload-build
    # time so the consumer can show which transports are candidates
    # for a ``config.txt`` flash.
    is_remora: bool = False


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
    entries carry their own HAL-facing fields (signal aliases for
    the digital path, ``pwm_pin`` / ``enable_pin`` for the analog
    path) plus the shared ``min_rpm`` / ``max_rpm`` clamps.

    The ``name`` field is the operator-facing label (chip text in
    the ToolPanel header). ``id`` is the canonical machine handle
    — same namespace policy as every other top-level list.

    Cross-references resolve into the matching top-level list by
    parent-list discriminator — ``sensor`` into
    ``temperature_sensors[].id``, ``fan`` into ``fans[].id``. No
    cross-reference exists for the spindle HAL pins (those are
    literal ``host:pin`` strings, not ids).
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str | None = None
    type: ToolType

    # ---- Spindle shared (digital + analog) ------------------------ #
    min_rpm: float | None = None
    max_rpm: float | None = None

    # ---- Spindle analog only --------------------------------------- #
    pwm_pin: str | None = None
    enable_pin: str | None = None

    # ---- Spindle digital only -------------------------------------- #
    # The HAL signal aliases the vfdmod driver expects. Populated
    # fields are wired live in the compiled ``machine.hal``; empty
    # fields fall back to ``# TODO`` placeholders so the operator
    # sees exactly which hooks still need manual configuration.
    signal_at_speed: str | None = None
    signal_forward: str | None = None
    signal_reverse: str | None = None
    signal_on: str | None = None
    signal_pwm: str | None = None
    signal_istop: str | None = None
    signal_estop: str | None = None
    signal_vfd_enable: str | None = None

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

    version: Literal["2.0"] = "2.0"
    machine: str
    source: str
    kinematics: str
    hal_type: str

    axes: list[Axis] = Field(default_factory=list)
    steppers: list[Stepper] = Field(default_factory=list)
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

    @model_validator(mode="after")
    def _validate_references(self) -> "HardwareJson":
        """Enforce every reference resolves into the right list.

        The check is run after the model is constructed so the
        per-field validators (id pattern, enums, etc.) have already
        failed-fast on the obvious problems. What's left is the
        graph-level consistency.
        """
        errors: list[str] = []

        # IDs are unique within each top-level list.
        for list_attr in (
            "axes",
            "steppers",
            "drivers",
            "endstops",
            "tools",
            "temperature_sensors",
            "fans",
        ):
            self._check_unique_ids(list_attr, errors)

        # Reference lookup tables — ``{id: index}`` for fast checks.
        steppers_idx = {s.id: i for i, s in enumerate(self.steppers)}
        drivers_idx = {d.id: i for i, d in enumerate(self.drivers)}
        sensors_idx = {
            s.id: i for i, s in enumerate(self.temperature_sensors)
        }
        fans_idx = {f.id: i for i, f in enumerate(self.fans)}
        endstops_idx = {e.id: i for i, e in enumerate(self.endstops)}

        # Every axis.steppers[i] must exist in steppers[]; every
        # ``axis.endstop`` must resolve into the top-level
        # ``endstops[]`` list. ``axis.endstop_pin`` is a free-form
        # pin string and does NOT require a matching record (it
        # is the inline Klipper form). Mutual exclusion between
        # ``endstop`` and ``endstop_pin`` lives on
        # :meth:`Axis._validate_endstop_exclusive`.
        for axis in self.axes:
            for stepper_id in axis.steppers:
                if stepper_id not in steppers_idx:
                    errors.append(
                        f"Axis '{axis.id}' references unknown stepper "
                        f"'{stepper_id}'."
                    )
            if axis.endstop is not None and axis.endstop not in endstops_idx:
                errors.append(
                    f"Axis '{axis.id}' references unknown endstop "
                    f"'{axis.endstop}'."
                )

        # Every stepper.driver must exist in drivers[].
        for stepper in self.steppers:
            if stepper.driver not in drivers_idx:
                errors.append(
                    f"Stepper '{stepper.id}' references unknown driver "
                    f"'{stepper.driver}'."
                )

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

        if errors:
            # Raise as a single ValueError so the consumer gets the
            # full list in one shot instead of fixing them one at a time.
            raise ValueError(
                "hardware.json v2 reference validation failed:\n  - "
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