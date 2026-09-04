"""Introspection of the preloaded HAL pin containers.

The machine.hal template must list *every* pin the ``webgui`` userspace
component exposes, together with a description of where it should be
connected. The containers already exist — the services preload them at
startup from the active ``hardware.json`` (see ``main.py``:

    tool_service.preload_hal_pins()
    sensor_service.preload_hal_pins()
    state_service.preload_hal_pins()
    HalPin.initialize_component()

) and by contract no pins are ever added at runtime. This module walks
those frozen dataclass containers (``SpindleDigitalPins``,
``SpindleAnalogPins``, ``HeaterPins``, ``ExtruderPins``,
``TemperaturePin``, ``EStopPin``) via :func:`dataclasses.fields` and
derives a flat, human-readable catalog:

* the concrete ``HalPin`` subclass determines direction —
  ``ReadOnlyDynamicHalPin`` registers ``HAL_IN`` (something must *drive*
  the pin: ``net <sig> => webgui.<pin>``), ``ReadWriteDynamicHalPin``
  registers ``HAL_OUT`` (the pin *drives* something:
  ``net <sig> <= webgui.<pin>``),
* ``StaticHalPin`` values are configuration constants (min/max RPM,
  temperature limits) — documented, never wired,
* ``UnconnectedHalPin`` slots are placeholders the runtime mappers
  deliberately left blank — listed for completeness.

The DTO dataclasses stay dumb; all introspection lives here.
Connection suggestions are a pure data table
(:data:`CONNECT_HINTS`) — documentation only, no runtime effect —
and name generic LinuxCNC HAL components (``stepgen.N.*``,
``pid.N.*``, ...), not the Remora-specific firmware pin space the
now-retired compiler pipeline used.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dtos.pins.HalPin import HalPin, HalDataType
from dtos.pins.ReadOnlyDynamicHalPin import ReadOnlyDynamicHalPin
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from dtos.pins.StaticHalPin import StaticHalPin
from dtos.pins.UnconnectedHalPin import UnconnectedHalPin

COMPONENT_NAME = "webgui"

GROUP_TOOLS = "tools"
GROUP_SENSORS = "sensors"
GROUP_STATE = "state"

#: Connection suggestions keyed by ``container class -> field name``.
#: Values are short operator-facing sentences; the rendered template
#: turns them into the ``net`` line shown next to each pin. Purely
#: documentation — nothing here executes at runtime.
CONNECT_HINTS: Dict[str, Dict[str, str]] = {
    "SpindleDigitalPins": {
        "target_rpm": "drive from the commanded speed source (PID output / speed target)",
        "actual_rpm": "drive from the VFD tachometer feedback (vfdmod.spindle-rpm-fb)",
        "is_connected": "drive from the VFD ready/connected bit",
        "error_count": "drive from the VFD error counter (hold at 0 when healthy)",
        "last_error": "drive from the VFD last-error register",
        "spindle_at_speed": "drive from vfdmod.spindle-at-speed",
        "spindle_forward": "drive from the forward run latch (halui.spindle.0.on / vfdmod)",
        "spindle_reverse": "drive from the reverse run latch (halui.spindle.0.on / vfdmod)",
        "absolute_master_override_enable": "sink into halui.spindle.override.enable",
        "absolute_master_override": "scale, then sink into halui.spindle.override.value",
        "override": "scale (x100), then sink into halui.spindle.override.scale",
    },
    "SpindleAnalogPins": {
        "analog_out": "sink into vfdmod.spindle-speed-cmd (or a pwm/scale chain)",
        "target_rpm": "drive from the commanded speed source",
    },
    "HeaterPins": {
        "target_temperature": "net as the PID setpoint; PID output -> heater drive (pid.N.command)",
        "actual_temperature": "net as the PID feedback from the thermistor input (pid.N.feedback)",
        "fan": "sink into the heater cooling-fan output",
    },
    "ExtruderPins": {
        "position": "net as the extruder stepgen position command (stepgen.N.position-cmd)",
    },
    "TemperaturePin": {
        "actual_temperature": "drive from the thermistor input (your ADC/thermistor reader's output)",
    },
    "EStopPin": {
        "pressed": "sink into halui.estop.request (webgui raises/lowers the estop)",
    },
}

#: Fallback suggestion when a field has no table entry.
_DEFAULT_HINT = "connect to the matching signal in your machine wiring"


@dataclass(frozen=True)
class PinDescriptor:
    """One wireable (or informational) HAL pin row in the catalog."""

    group: str
    container: str
    owner_id: str
    field: str
    pin_name: str  # full HAL name, e.g. "webgui.spindle-at-speed0" ("" if n/a)
    hal_type: str  # "BIT" | "FLOAT" | "S32" | "U32" | ""
    direction: str  # "in" | "out" | "" (static / unconnected)
    kind: str  # "readonly" | "readwrite" | "static" | "unconnected"
    value: str  # stringified constant for static pins, else ""
    description: str
    connect_hint: str

    @property
    def short_pin(self) -> str:
        """Pin name without the ``webgui.`` component prefix."""
        if not self.pin_name:
            return ""
        prefix = f"{COMPONENT_NAME}."
        return self.pin_name[len(prefix):] if self.pin_name.startswith(prefix) else self.pin_name


@dataclass(frozen=True)
class PinContainerDescriptor:
    """All pins of one pin-container dataclass instance (e.g. one tool)."""

    group: str
    container: str
    owner_id: str
    pins: List[PinDescriptor] = field(default_factory=list)


@dataclass(frozen=True)
class PinCatalog:
    """Complete snapshot of the ``webgui`` HAL component surface."""

    containers: List[PinContainerDescriptor] = field(default_factory=list)

    def total_pins(self) -> int:
        return sum(len(container.pins) for container in self.containers)

    def groups(self) -> List[str]:
        seen: List[str] = []
        for container in self.containers:
            if container.group not in seen:
                seen.append(container.group)
        return seen

    def for_group(self, group: str) -> List[PinContainerDescriptor]:
        return [c for c in self.containers if c.group == group]


def _type_label(hal_type: Optional[HalDataType]) -> str:
    return hal_type.value if hal_type is not None else ""


def _hint_for(container: str, field_name: str) -> str:
    return CONNECT_HINTS.get(container, {}).get(field_name, _DEFAULT_HINT)


def _describe_leaf(
    group: str,
    container: str,
    owner_id: str,
    field_name: str,
    pin: HalPin[Any],
) -> PinDescriptor:
    """Build one descriptor from a concrete (non-container) HalPin value."""
    if isinstance(pin, UnconnectedHalPin):
        return PinDescriptor(
            group=group,
            container=container,
            owner_id=owner_id,
            field=field_name,
            pin_name="",
            hal_type="",
            direction="",
            kind="unconnected",
            value="",
            description="placeholder the runtime mapper left unconnected",
            connect_hint="no wiring required",
        )
    if isinstance(pin, StaticHalPin):
        return PinDescriptor(
            group=group,
            container=container,
            owner_id=owner_id,
            field=field_name,
            pin_name="",
            hal_type="",
            direction="",
            kind="static",
            value=repr(pin.value),
            description="configuration constant (never wired into HAL)",
            connect_hint="no wiring — value is baked into the runtime",
        )
    if isinstance(pin, ReadOnlyDynamicHalPin):
        return PinDescriptor(
            group=group,
            container=container,
            owner_id=owner_id,
            field=field_name,
            pin_name=f"{COMPONENT_NAME}.{pin.pin}",
            hal_type=_type_label(pin.hal_type),
            direction="in",
            kind="readonly",
            value="",
            description=pin.description,
            connect_hint=_hint_for(container, field_name),
        )
    if isinstance(pin, ReadWriteDynamicHalPin):
        return PinDescriptor(
            group=group,
            container=container,
            owner_id=owner_id,
            field=field_name,
            pin_name=f"{COMPONENT_NAME}.{pin.pin}",
            hal_type=_type_label(pin.hal_type),
            direction="out",
            kind="readwrite",
            value="",
            description=pin.description,
            connect_hint=_hint_for(container, field_name),
        )
    # Unknown future HalPin subclass — surface it honestly.
    return PinDescriptor(
        group=group,
        container=container,
        owner_id=owner_id,
        field=field_name,
        pin_name="",
        hal_type="",
        direction="",
        kind=type(pin).__name__,
        value="",
        description="unrecognised HalPin subclass",
        connect_hint=_DEFAULT_HINT,
    )


def _is_pin_container(value: Any) -> bool:
    return dataclasses.is_dataclass(value) and not isinstance(value, HalPin) and not isinstance(
        value, type
    )


def _describe_container(
    group: str,
    container_obj: Any,
) -> PinContainerDescriptor:
    """Walk one pin-container dataclass instance (recursing into nested ones)."""
    container_name = type(container_obj).__name__
    owner_id = str(getattr(container_obj, "id", "") or "")
    pins: List[PinDescriptor] = []

    for dc_field in dataclasses.fields(container_obj):
        if dc_field.name == "id":
            continue
        value = getattr(container_obj, dc_field.name)
        if _is_pin_container(value):
            # Nested container (e.g. ExtruderPins.heater: HeaterPins) —
            # recurse and prefix the leaf field names so the catalog
            # stays flat. Leaf descriptors keep their own container
            # class so the hint table lookup stays precise.
            nested = _describe_container(group, value)
            for pin in nested.pins:
                pins.append(
                    dataclasses.replace(pin, field=f"{dc_field.name}.{pin.field}")
                )
            continue
        if not isinstance(value, HalPin):
            continue
        pins.append(
            _describe_leaf(group, container_name, owner_id, dc_field.name, value)
        )

    return PinContainerDescriptor(
        group=group,
        container=container_name,
        owner_id=owner_id,
        pins=pins,
    )


def build_catalog_from_containers(
    tools: List[Any],
    sensors: List[Any],
    state: List[Any],
) -> PinCatalog:
    """Introspect already-built pin containers (no service access)."""
    containers: List[PinContainerDescriptor] = []
    for group, items in (
        (GROUP_TOOLS, tools),
        (GROUP_SENSORS, sensors),
        (GROUP_STATE, state),
    ):
        for item in items or []:
            if item is None:
                continue
            containers.append(_describe_container(group, item))
    return PinCatalog(containers=containers)


def _build_default_containers() -> tuple[List[Any], List[Any], List[Any]]:
    """Build the pin containers straight from the active ``hardware.json``.

    The pre-two-service-split version pulled the cached containers
    from the machine services (``ToolsService`` / ``TemperatureService``
    / ``StateService``); those now live in the machine backend and are
    not importable from the system service. The same factories and
    mappers they use at preload time are part of the shared layer, so
    the catalog rebuilds the containers here — same DTOs, same logic.
    """
    from dtos.EStopDto import EStopPin
    from dtos.pins.HalPin import HalDataType
    from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
    from factories.tools.ToolHalPinFactory import ToolHalPinFactory
    from mappers.temperature.TemperatureSensorMapper import (
        TemperatureSensorMapper,
    )
    from mappers.tools.HeaterMapper import HeaterMapper
    from temperature_config_mapper import get_temperature_sensors
    from tools_config_mapper import get_all_heater, get_tools

    tools = [
        pin_map
        for pin_map in (ToolHalPinFactory.create(tool) for tool in get_tools())
        if pin_map is not None
    ]

    sensors: List[Any] = []
    used_sensor_ids = set()
    for heater in get_all_heater():
        pin_map = HeaterMapper.from_dict_to_HeaterPins(heater)
        if pin_map is not None:
            sensors.append(pin_map)
            sensor_id = heater.get("sensor") or heater.get("id")
            if sensor_id:
                used_sensor_ids.add(sensor_id)
    for sensor in get_temperature_sensors():
        if sensor.get("id") in used_sensor_ids:
            continue
        sensor_pin_map = TemperatureSensorMapper.from_dict_to_TemperaturePins(sensor)
        if sensor_pin_map is not None:
            sensors.append(sensor_pin_map)

    state = [EStopPin("estop", ReadWriteDynamicHalPin("estop", HalDataType.BIT, ""))]
    return tools, sensors, state


def build_pin_catalog(
    tool_containers: Optional[List[Any]] = None,
    sensor_containers: Optional[List[Any]] = None,
    state_containers: Optional[List[Any]] = None,
) -> PinCatalog:
    """Collect the catalog for the ``webgui`` HAL component.

    Containers are rebuilt from the active ``hardware.json`` via the
    shared factories/mappers unless the ``*_containers`` overrides are
    supplied (tests pass pre-built containers to avoid touching any
    config file).
    """
    if (
        tool_containers is None
        or sensor_containers is None
        or state_containers is None
    ):
        default_tools, default_sensors, default_state = _build_default_containers()

    tools = (
        tool_containers
        if tool_containers is not None
        else default_tools
    )
    sensors = (
        sensor_containers
        if sensor_containers is not None
        else default_sensors
    )
    state = (
        state_containers
        if state_containers is not None
        else default_state
    )
    return build_catalog_from_containers(tools, sensors, state)


__all__ = [
    "COMPONENT_NAME",
    "GROUP_SENSORS",
    "GROUP_STATE",
    "GROUP_TOOLS",
    "PinCatalog",
    "PinContainerDescriptor",
    "PinDescriptor",
    "CONNECT_HINTS",
    "build_catalog_from_containers",
    "build_pin_catalog",
]
