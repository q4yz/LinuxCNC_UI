"""Typed views of the ACE Pro's answers. Parsing is lenient: the protocol
is reverse-engineered, so unknown fields are kept (``raw``) and missing
ones get neutral defaults instead of failing."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: ``rfid`` values in slot and filament info.
RFID_STATES = {0: "not found", 1: "failed", 2: "identified", 3: "identifying"}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _color(value: Any) -> tuple[int, int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        r, g, b = (max(0, min(255, _int(c))) for c in value[:3])
        return (r, g, b)
    return None


@dataclass(frozen=True)
class AceInfo:
    model: str
    firmware: str
    boot_firmware: str
    slots: int
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def parse(cls, data: dict[str, Any]) -> AceInfo:
        return cls(
            model=str(data.get("model", "")),
            firmware=str(data.get("firmware", "")),
            boot_firmware=str(data.get("boot_firmware", "")),
            slots=_int(data.get("slots"), 4) or 4,
            raw=dict(data),
        )


@dataclass(frozen=True)
class SlotStatus:
    index: int
    #: "ready" (filament there), "empty", or what the firmware says
    status: str
    sku: str = ""
    brand: str = ""
    type: str = ""
    color: tuple[int, int, int] | None = None
    rfid: int = 0

    @property
    def has_filament(self) -> bool:
        return self.status == "ready"

    @classmethod
    def parse(cls, data: dict[str, Any], default_index: int = 0) -> SlotStatus:
        return cls(
            index=_int(data.get("index"), default_index),
            status=str(data.get("status", "")),
            sku=str(data.get("sku", "")),
            brand=str(data.get("brand", "")),
            type=str(data.get("type", "")),
            color=_color(data.get("color")),
            rfid=_int(data.get("rfid")),
        )


@dataclass(frozen=True)
class DryerStatus:
    #: "stop" or "drying"
    status: str
    target_temp: float | None = None
    duration_min: float | None = None
    remain_min: float | None = None

    @property
    def drying(self) -> bool:
        return self.status == "drying"

    @classmethod
    def parse(cls, data: Any) -> DryerStatus:
        data = data if isinstance(data, dict) else {}
        return cls(
            status=str(data.get("status", "stop")),
            target_temp=_float(data.get("target_temp")),
            duration_min=_float(data.get("duration")),
            remain_min=_float(data.get("remain_time")),
        )


@dataclass(frozen=True)
class AceStatus:
    #: "ready" or "busy"
    status: str
    #: what it is busy with: "feeding", "unwinding", "shifting", or ""
    action: str
    temp: float | None
    fan_speed: float | None
    feed_assist_count: int
    dryer: DryerStatus
    slots: tuple[SlotStatus, ...]
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    @classmethod
    def parse(cls, data: dict[str, Any]) -> AceStatus:
        slots = data.get("slots") if isinstance(data.get("slots"), list) else []
        return cls(
            status=str(data.get("status", "")),
            action=str(data.get("action", "") or ""),
            temp=_float(data.get("temp")),
            fan_speed=_float(data.get("fan_speed")),
            feed_assist_count=_int(data.get("feed_assist_count")),
            dryer=DryerStatus.parse(data.get("dryer_status")),
            slots=tuple(SlotStatus.parse(s, i) for i, s in enumerate(slots) if isinstance(s, dict)),
            raw=dict(data),
        )


@dataclass(frozen=True)
class FilamentInfo:
    index: int
    sku: str
    brand: str
    type: str
    color: tuple[int, int, int] | None
    rfid: int
    extruder_temp: tuple[float | None, float | None]
    hotbed_temp: tuple[float | None, float | None]
    diameter: float | None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def rfid_text(self) -> str:
        return RFID_STATES.get(self.rfid, str(self.rfid))

    @classmethod
    def parse(cls, data: dict[str, Any]) -> FilamentInfo:
        def span(key: str) -> tuple[float | None, float | None]:
            value = data.get(key)
            if not isinstance(value, dict):
                return (None, None)
            return (_float(value.get("min")), _float(value.get("max")))

        return cls(
            index=_int(data.get("index")),
            sku=str(data.get("sku", "")),
            brand=str(data.get("brand", "")),
            type=str(data.get("type", "")),
            color=_color(data.get("color")),
            rfid=_int(data.get("rfid")),
            extruder_temp=span("extruder_temp"),
            hotbed_temp=span("hotbed_temp"),
            diameter=_float(data.get("diameter")),
            raw=dict(data),
        )


__all__ = ["RFID_STATES", "AceInfo", "AceStatus", "DryerStatus", "FilamentInfo", "SlotStatus"]
