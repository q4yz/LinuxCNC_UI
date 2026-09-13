"""Shared helper for reading the active ``hardware.json``'s ``fans[]``.

Same pattern as ``temperature_config_mapper.get_temperature_sensors`` —
one thin, testable wrapper over :class:`HardwareConfigService` so a
missing file or corrupt JSON returns an empty list instead of
crashing the caller.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from services.HardwareConfigService import HardwareConfigService


def get_fans(active_path: Path | None = None) -> List[Dict[str, Any]]:
    config_service = HardwareConfigService(active_path)
    raw_fans = config_service.get_fans()

    out: List[Dict[str, Any]] = []
    for entry in raw_fans:
        if not isinstance(entry, dict):
            continue
        if not isinstance(entry.get("id"), str) or not entry["id"]:
            continue
        out.append(entry)
    return out


__all__ = ["get_fans"]
