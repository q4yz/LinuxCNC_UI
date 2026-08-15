"""Shared helper for reading the active ``hardware.json`` ``tools[]``.

The tools module's ``GET /tools`` endpoint derives its response
from the active ``hardware.json`` ``tools[]`` list. The temperature
module's sibling helper (:func:`services.hardware_loader.load_active_heaters`)
already consumes the same file but only exposes sensor ids — the
tools module needs the full operator-facing record (id, name, type,
HAL hooks, min/max clamps, …) for every tool the machine declares.

A single helper keeps the path-resolution and JSON-parse logic in
one place. The router calls :func:`load_active_tools` so a future
move to a different active root only touches this module.

Failure modes (missing file, corrupt JSON, missing ``tools`` key,
``tools`` not a list, every entry lacking a usable ``id``) return
an empty list — the router then serves ``{"tools": []}`` and the
ToolPanel renders the "No tools configured yet" empty state
instead of crashing on boot.

The v2 hardware.json model (see
:mod:`backend.modules.machineconfig.models.hardware_json_models`)
already validates every entry's shape and resolves the
``tool.sensor`` / ``tool.fan`` cross-references at compile time,
so this loader intentionally performs no further validation —
it is a pure read.

The :class:`SpindleDigitalPins` dataclass and :func:`get_spindle_hal_pin_map`
helper expose the HAL signal aliases every digital spindle declares.
The runtime service addresses spindles by canonical id (``spindle_digital``
for the bare form, ``spindle_digital_test`` for ``[spindle test]``, ...)
and writes the ``signal_*`` HAL pins via ``setp`` (enables) or ``net``
(net signals). A ``None`` pin means "not wired" — the runtime skips it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Any

from modules.tools.dtos.digital_spindle_dto import SpindleDigitalPins
from services.hardware_config_service import HardwareConfigService

logger = logging.getLogger("backend.modules.tools.tools_loader")

def get_tools(active_path: Path | None = None,) -> List[dict]:
    out: List[dict] = []
    config_service = HardwareConfigService(active_path)
    tools_list = config_service.get_tools()

    for entry in tools_list:
        if not isinstance(entry, dict):
            continue
        if not isinstance(entry.get("id"), str) or not entry["id"]:
            continue
        out.append(entry)
    return out


__all__ = ["get_tools", "get_spindle_hal_pin_map"]


def get_spindle_hal_pin_map(spindle_id: str,active_path: Path | None = None) -> SpindleDigitalPins:
    pin_maps = get_spindle_hal_pin_maps(active_path)

    if spindle_id not in pin_maps:
        raise KeyError(
            f"Spindle ID '{spindle_id}' not found in the active hardware configuration."
        )

    return pin_maps[spindle_id]

def get_spindle_hal_pin_maps(active_path: Path | None = None) -> Dict[str, SpindleDigitalPins]:
    config_service = HardwareConfigService(active_path)
    tools_list = config_service.get_tools()

    out: Dict[str, SpindleDigitalPins] = {}
    for tool in tools_list:
        if _is_digital_spindle(tool):
            out[tool.get("id")] = SpindleDigitalPins.from_dict(tool)
    return out

def _is_digital_spindle(tool: Any) -> bool:
    if not isinstance(tool, dict):
        return False
    if tool.get("type") != "spindle_digital":
        return False
    tool_id = tool.get("id")
    if not isinstance(tool_id, str) or not tool_id:
        return False
    return True

