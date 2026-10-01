"""Shared helper for reading the active ``hardware.json``'s ``mcus[]``.

Same pattern as ``fans_config_mapper.get_fans`` — one thin, testable
wrapper over :class:`HardwareConfigService` so a missing file or
corrupt JSON returns an empty list instead of crashing the caller.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from services.HardwareConfigService import HardwareConfigService


def get_mcus(active_path: Path | None = None) -> List[Dict[str, Any]]:
    config_service = HardwareConfigService(active_path)

    out: List[Dict[str, Any]] = []
    for entry in config_service.get_mcus():
        if not isinstance(entry, dict):
            continue
        if not isinstance(entry.get("id"), str) or not entry["id"]:
            continue
        out.append(entry)
    return out


__all__ = ["get_mcus"]
