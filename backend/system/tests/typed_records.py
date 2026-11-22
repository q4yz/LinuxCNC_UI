"""Dict fixtures -> the typed hardware.json records the HAL compiler's
mappers take (``services.halcompiler.HardwareRecords``). The tests keep
their short dict fixtures; these fill what a record requires and the
fixture leaves out."""
from __future__ import annotations

from typing import Any, Mapping

from models.machineconfig.HalFragmentModels import RouterMcu
from models.machineconfig.HardwareJsonModels import (
    Axis,
    Driver,
    Endstop,
    Estop,
    McuInfo,
    Probe,
    Stepper,
    ToolLengthSensor,
)

#: The router tests' old private keys on the MCU dict -> RouterMcu fields.
_ROUTER_KEYS = {
    "_can_status_bit": "can_status_bit",
    "_estop_fault": "estop_fault",
    "_spindle_min_rpm": "spindle_min_rpm",
    "_spindle_max_rpm": "spindle_max_rpm",
}


def mcu(record: Mapping[str, Any], connection: str = "remora-spi") -> McuInfo:
    data = {"id": "mcu", "connection": connection, **record}
    params = data.pop("parameters", None) or {}
    if "chip" in params:
        data["chip"] = params["chip"]
    for key in _ROUTER_KEYS:
        data.pop(key, None)
    return McuInfo.model_validate(data)


def router_mcu(record: Mapping[str, Any], connection: str = "remora-spi") -> RouterMcu:
    extra = {field: record[key] for key, field in _ROUTER_KEYS.items() if key in record}
    return RouterMcu(mcu=mcu(record, connection), **extra)


def mcus_by_id(records: Mapping[str, Mapping[str, Any]]) -> dict[str, McuInfo]:
    return {k: mcu({"id": k, **v}, v.get("connection", "remora-spi")) for k, v in records.items()}


def axis(record: Mapping[str, Any]) -> Axis:
    return Axis.model_validate(record)


def joint(record: Mapping[str, Any]) -> Stepper:
    return Stepper.model_validate(record)


def joints(records: list[Mapping[str, Any]]) -> list[Stepper]:
    return [joint(r) for r in records]


def endstops_by_id(records: Mapping[str, Mapping[str, Any]]) -> dict[str, Endstop]:
    return {k: Endstop.model_validate({"id": k, **v}) for k, v in records.items()}


def drivers_by_id(records: Mapping[str, Mapping[str, Any]]) -> dict[str, Driver]:
    return {k: Driver.model_validate({"id": k, **v}) for k, v in records.items()}


def estop(record: Mapping[str, Any] | None) -> Estop | None:
    return Estop.model_validate(record) if record is not None else None


def probe(record: Mapping[str, Any] | None) -> Probe | None:
    return Probe.model_validate(record) if record is not None else None


def tool_length_sensor(record: Mapping[str, Any] | None) -> ToolLengthSensor | None:
    return ToolLengthSensor.model_validate(record) if record is not None else None
