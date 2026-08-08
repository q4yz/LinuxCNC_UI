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

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------- #
# Entity models                                                           #
# ---------------------------------------------------------------------- #


class Axis(BaseModel):
    """A kinematic axis. Owns a list of steppers (multi-motor axes)
    and a list of endstop records (the kinematic constraints)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    steppers: list[str]
    endstops: list[str] = Field(default_factory=list)


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
    """A logical endstop record.

    The same physical switch can appear in three records with
    different ``type`` values: ``endstop`` (the actual endstop),
    ``homing`` (the homing switch), ``ignore`` (used only by macros,
    not by kinematic constraints). All three records share the
    same ``endstop_id`` (the Klipper ``[endstop_switch NAME]``
    section name) and the same ``pin``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    endstop_id: str
    stepper: str
    pin: str
    pos: float
    type: Literal["endstop", "homing", "ignore"]


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
    """A single output fan."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    pin: str


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
            for endstop_id in axis.endstops:
                if endstop_id not in endstops_idx:
                    errors.append(
                        f"Axis '{axis.id}' references unknown endstop "
                        f"'{endstop_id}'."
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
                    f"Endstop '{endstop.id}' (switch '{endstop.endstop_id}') "
                    f"references unknown stepper '{endstop.stepper}'."
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

        # Every endstop_id must have at least one matching endstop
        # record. The "type" field is the role discriminator; the
        # endstop_id is the switch identity. A switch with no
        # record at all is a dangling reference.
        swiss_role_coverage: dict[str, set[Literal["endstop", "homing", "ignore"]]] = {}
        for endstop in self.endstops:
            swiss_role_coverage.setdefault(endstop.endstop_id, set()).add(
                endstop.type
            )
        for switch_id in swiss_role_coverage:
            roles = swiss_role_coverage[switch_id]
            if "endstop" not in roles:
                errors.append(
                    f"Switch '{switch_id}' has no endstop record; "
                    f"only roles {sorted(roles)} declared."
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
    "Fan",
    "HardwareJson",
    "Heater",
    "Stepper",
    "TemperatureSensor",
    "model_validate",
    "to_dict",
]
