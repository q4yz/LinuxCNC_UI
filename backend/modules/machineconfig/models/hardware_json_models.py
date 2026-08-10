"""Pydantic models for the canonical ``hardware.json`` v2 shape.

The ``hardware.json`` payload is the machine's hardware contract —
emitted by the Klipper compiler, consumed by the runtime (the
temperature module seeds its sensors from ``temperature_sensors``,
the jog watchdog reads the endstop records, etc.).

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
exists today; ``pressure_sensors`` and ``flow_sensors`` are
forward-looking slots that the cross-reference validator will
not see (each new kind is a separate top-level list with its own
``id`` namespace). The id values themselves carry no type prefix
— e.g. an id is ``sensor_extruder`` not ``temp_sensor_extruder``
— because the parent list is the type discriminator. ``heater.sensor``
resolves into ``temperature_sensors[].id``; a future
``heater.pressure_sensor`` would resolve into ``pressure_sensors[].id``.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# Type alias for the endstop behaviour tag. ``None`` means the
# endstop is exposed to user macros only — it is NOT a kinematic
# constraint and does NOT participate in homing or e-stop logic.
# ``"Estop"`` flags a switch that kills motion when triggered.
# ``"Home"`` flags a switch used by LinuxCNC's homing sequence.
EndstopType = Optional[Literal["Estop", "Home"]]


# ---------------------------------------------------------------------- #
# Entity models                                                           #
# ---------------------------------------------------------------------- #


class Axis(BaseModel):
    """A kinematic axis. Owns a list of steppers (multi-motor axes)
    and a list of inline endstop views (the kinematic constraints).

    The inline ``endstops`` entries carry only ``{id, type, pos}`` —
    enough for the runtime to find the right record and route it
    to the appropriate HAL signal. The full record (with ``pin``
    and ``stepper``) lives at the top-level ``endstops`` array so
    HAL wiring stays centralised; the inline entries reference
    those records by ``id``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    steppers: list[str]
    endstops: list["EndstopView"] = Field(default_factory=list)


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


class EndstopView(BaseModel):
    """Inline endstop entry embedded inside :class:`Axis.endstops`.

    Carries only the fields the runtime needs to find the record
    and decide how to wire it (``id``, ``type``, ``pos``). The full
    record (with ``pin`` / ``stepper``) lives at the top-level
    ``endstops`` array.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: EndstopType = None
    pos: float


class Endstop(BaseModel):
    """Full endstop record at the top-level ``endstops`` array.

    Each Klipper ``[endstop_switch NAME]`` produces ONE record per
    switch. The ``type`` field tells the runtime how to use the
    switch:

    * ``"Estop"`` — the switch kills motion when triggered.
    * ``"Home"`` — the switch is used by LinuxCNC's homing sequence.
    * ``None`` — the switch is macros-only (no kinematic role).

    ``pos`` is the position of the switch on the axis (in user
    units), so the runtime can validate the homing sequence.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: EndstopType = None
    pos: float
    stepper: str
    pin: str


class Heater(BaseModel):
    """A temperature-controlled heater.

    References a temperature sensor by id. The reference resolves
    into ``temperature_sensors[].id`` — not into any future
    ``pressure_sensors`` or ``flow_sensors`` list the project may
    add later. The type discriminator is the parent list name.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    sensor: str | None = None
    fan: str | None = None
    heater_pin: str
    control: str
    min_temp: float | None = None
    max_temp: float | None = None


class TemperatureSensor(BaseModel):
    """A single temperature sensor (thermistor, RTD, etc.).

    Lives in the ``temperature_sensors`` top-level list. The list
    name is the type discriminator — when pressure and flow sensors
    land later, they will live in their own lists and not share
    ids with this one.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    pin: str
    type: str | None = None


class Fan(BaseModel):
    """A single output fan.

    ``max_power`` (0.0–1.0) is the PWM duty-cycle ceiling. The
    Remora board JSON uses an 8-bit ``pwm_max`` field; the runtime
    scales ``max_power`` to 0–255 before pushing the value into the
    firmware. Persisting the float here keeps the round-trip
    deterministic (no need to re-read ``config.txt`` to recover the
    duty-cycle cap).
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    pin: str
    max_power: float | None = None


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
    heaters: list[Heater] = Field(default_factory=list)
    temperature_sensors: list[TemperatureSensor] = Field(default_factory=list)
    fans: list[Fan] = Field(default_factory=list)

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
            "heaters",
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
        heaters_idx = {h.id: i for i, h in enumerate(self.heaters)}

        # Every axis.steppers[i] must exist in steppers[].
        for axis in self.axes:
            for stepper_id in axis.steppers:
                if stepper_id not in steppers_idx:
                    errors.append(
                        f"Axis '{axis.id}' references unknown stepper "
                        f"'{stepper_id}'."
                    )
            # The inline ``axis.endstops[*]`` entries reference
            # the top-level ``endstops[]`` records by id; validate
            # the link so a renamed record surfaces here instead of
            # at runtime.
            for view in axis.endstops:
                if view.id not in endstops_idx:
                    errors.append(
                        f"Axis '{axis.id}' inline endstop '{view.id}' "
                        f"does not match any top-level endstop record."
                    )

        # Every stepper.driver must exist in drivers[].
        for stepper in self.steppers:
            if stepper.driver not in drivers_idx:
                errors.append(
                    f"Stepper '{stepper.id}' references unknown driver "
                    f"'{stepper.driver}'."
                )

        # Every endstop.stepper must exist in steppers[].
        for endstop in self.endstops:
            if endstop.stepper not in steppers_idx:
                errors.append(
                    f"Endstop '{endstop.id}' references unknown stepper "
                    f"'{endstop.stepper}'."
                )

        # Every heater.sensor must exist in temperature_sensors[].
        # A pressure sensor is not a temperature sensor even if the
        # pin matches — the parent list is the type discriminator.
        for heater in self.heaters:
            if heater.sensor is not None and heater.sensor not in sensors_idx:
                errors.append(
                    f"Heater '{heater.id}' references unknown temperature "
                    f"sensor '{heater.sensor}'."
                )
            if heater.fan is not None and heater.fan not in fans_idx:
                errors.append(
                    f"Heater '{heater.id}' references unknown fan "
                    f"'{heater.fan}'."
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


__all__ = [
    "Axis",
    "Driver",
    "Endstop",
    "EndstopType",
    "EndstopView",
    "Fan",
    "HardwareJson",
    "Heater",
    "Stepper",
    "TemperatureSensor",
    "model_validate",
    "to_dict",
]
