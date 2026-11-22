"""Typed records of a ``hardware.json`` payload (the HAL compiler, the
machine backend's calibration / homing, the G-code converter).

The payload itself stays a plain dict (no :class:`HardwareJson` around
it): only the records the mappers work on are validated into their
models, so a mapper reads ``led.chain_count`` instead of
``int(led.get("chain_count") or 1)``, and a default lives in one place,
the model. A record that is not a dict is skipped (as before); a dict
that is not a valid record raises :class:`pydantic.ValidationError`.

:class:`MachineValidator` keeps reading the raw dicts: its job is to
report what is wrong with an untyped payload, not to stop at the first
field that does not validate.
"""
from __future__ import annotations

from typing import Any, Mapping, TypeVar

from pydantic import BaseModel

from models.machineconfig.HardwareJsonModels import (
    Adxl345,
    Axis,
    BedMesh,
    Driver,
    Endstop,
    Estop,
    Fan,
    FilamentChange,
    FirmwareRetraction,
    HomingOverride,
    InputPin,
    InputShaper,
    Led,
    McuInfo,
    OutputPin,
    Probe,
    SkewCorrection,
    Stepper,
    TemperatureSensor,
    Tool,
    ToolLengthSensor,
    ZTilt,
    ZVirtualEndstop,
)

M = TypeVar("M", bound=BaseModel)


class HardwareRecords:
    @staticmethod
    def many(payload: Mapping[str, Any], key: str, model: type[M]) -> list[M]:
        return [model.model_validate(r) for r in payload.get(key) or [] if isinstance(r, dict)]

    @staticmethod
    def one(payload: Mapping[str, Any], key: str, model: type[M]) -> M | None:
        record = payload.get(key)
        return model.model_validate(record) if isinstance(record, dict) else None

    # -- lists ------------------------------------------------------------- #

    @staticmethod
    def axes(payload: Mapping[str, Any]) -> list[Axis]:
        return HardwareRecords.many(payload, "axes", Axis)

    @staticmethod
    def joints(payload: Mapping[str, Any]) -> list[Stepper]:
        return HardwareRecords.many(payload, "joints", Stepper)

    @staticmethod
    def drivers(payload: Mapping[str, Any]) -> list[Driver]:
        return HardwareRecords.many(payload, "drivers", Driver)

    @staticmethod
    def endstops(payload: Mapping[str, Any]) -> list[Endstop]:
        return HardwareRecords.many(payload, "endstops", Endstop)

    @staticmethod
    def tools(payload: Mapping[str, Any]) -> list[Tool]:
        return HardwareRecords.many(payload, "tools", Tool)

    @staticmethod
    def temperature_sensors(payload: Mapping[str, Any]) -> list[TemperatureSensor]:
        return HardwareRecords.many(payload, "temperature_sensors", TemperatureSensor)

    @staticmethod
    def fans(payload: Mapping[str, Any]) -> list[Fan]:
        return HardwareRecords.many(payload, "fans", Fan)

    @staticmethod
    def mcus(payload: Mapping[str, Any]) -> list[McuInfo]:
        return HardwareRecords.many(payload, "mcus", McuInfo)

    @staticmethod
    def leds(payload: Mapping[str, Any]) -> list[Led]:
        return HardwareRecords.many(payload, "leds", Led)

    @staticmethod
    def output_pins(payload: Mapping[str, Any]) -> list[OutputPin]:
        return HardwareRecords.many(payload, "output_pins", OutputPin)

    @staticmethod
    def input_pins(payload: Mapping[str, Any]) -> list[InputPin]:
        return HardwareRecords.many(payload, "input_pins", InputPin)

    # -- single sections ---------------------------------------------------- #

    @staticmethod
    def estop(payload: Mapping[str, Any]) -> Estop | None:
        return HardwareRecords.one(payload, "estop", Estop)

    @staticmethod
    def probe(payload: Mapping[str, Any]) -> Probe | None:
        return HardwareRecords.one(payload, "probe", Probe)

    @staticmethod
    def tool_length_sensor(payload: Mapping[str, Any]) -> ToolLengthSensor | None:
        return HardwareRecords.one(payload, "tool_length_sensor", ToolLengthSensor)

    @staticmethod
    def bed_mesh(payload: Mapping[str, Any]) -> BedMesh | None:
        return HardwareRecords.one(payload, "bed_mesh", BedMesh)

    @staticmethod
    def z_tilt(payload: Mapping[str, Any]) -> ZTilt | None:
        return HardwareRecords.one(payload, "z_tilt", ZTilt)

    @staticmethod
    def z_virtual_endstop(payload: Mapping[str, Any]) -> ZVirtualEndstop | None:
        return HardwareRecords.one(payload, "z_virtual_endstop", ZVirtualEndstop)

    @staticmethod
    def firmware_retraction(payload: Mapping[str, Any]) -> FirmwareRetraction | None:
        return HardwareRecords.one(payload, "firmware_retraction", FirmwareRetraction)

    @staticmethod
    def filament_change(payload: Mapping[str, Any]) -> FilamentChange | None:
        return HardwareRecords.one(payload, "filament_change", FilamentChange)

    @staticmethod
    def homing_override(payload: Mapping[str, Any]) -> HomingOverride | None:
        return HardwareRecords.one(payload, "homing_override", HomingOverride)

    @staticmethod
    def input_shaper(payload: Mapping[str, Any]) -> InputShaper | None:
        return HardwareRecords.one(payload, "input_shaper", InputShaper)

    @staticmethod
    def skew_correction(payload: Mapping[str, Any]) -> SkewCorrection | None:
        return HardwareRecords.one(payload, "skew_correction", SkewCorrection)

    @staticmethod
    def adxl345(payload: Mapping[str, Any]) -> Adxl345 | None:
        return HardwareRecords.one(payload, "adxl345", Adxl345)


__all__ = ["HardwareRecords"]
