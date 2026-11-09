"""Demo heaters for the mock (no LinuxCNC / HAL): an extruder and a
heated bed, so the Tools panel and the temperature plot have something
to show on a development PC whose machine has no heaters (a CNC
profile, or no machine at all).

Added only when the active ``hardware.json`` declares no extruder and
no heated bed, and only in mock mode. ``LINUXCNC_UI_MOCK_DEMO_TOOLS=0``
turns it off. The mock simulates them like configured ones
(:class:`MockHeater`: heats at 2 °C/s, cools at 0.5 °C/s).
"""
from __future__ import annotations

import copy
import os
from typing import Any, Dict, List

ENV_FLAG = "LINUXCNC_UI_MOCK_DEMO_TOOLS"

DEMO_TOOLS = [
    {"id": "extruder", "type": "extruder", "sensor": "extruder", "min_temp": 0.0, "max_temp": 280.0, "demo": True},
    {"id": "heater_bed", "type": "heated_bed", "sensor": "bed", "min_temp": 0.0, "max_temp": 120.0, "demo": True},
]
DEMO_SENSORS = [
    {"id": "extruder", "pin": "mock", "type": "Generic 3950", "demo": True},
    {"id": "bed", "pin": "mock", "type": "Generic 3950", "demo": True},
]
_HEATING = ("extruder", "heated_bed", "heater")


def enabled() -> bool:
    return os.environ.get(ENV_FLAG, "1").strip().lower() not in ("0", "false", "no", "off")


def with_demo_tools(payload: Dict[str, Any]) -> Dict[str, Any]:
    """``payload`` plus the demo extruder and bed when it has no heater
    (a copy; ``payload`` itself is left alone)."""
    if not enabled():
        return payload
    raw_tools = payload.get("tools")
    tools: List[Any] = raw_tools if isinstance(raw_tools, list) else []
    if any(isinstance(t, dict) and t.get("type") in _HEATING for t in tools):
        return payload
    out = dict(payload)
    taken = {t.get("id") for t in tools if isinstance(t, dict)}
    out["tools"] = list(tools) + [copy.deepcopy(t) for t in DEMO_TOOLS if t["id"] not in taken]
    raw_sensors = payload.get("temperature_sensors")
    sensors: List[Any] = raw_sensors if isinstance(raw_sensors, list) else []
    taken_sensors = {s.get("id") for s in sensors if isinstance(s, dict)}
    out["temperature_sensors"] = list(sensors) + [
        copy.deepcopy(s) for s in DEMO_SENSORS if s["id"] not in taken_sensors
    ]
    return out


__all__ = ["DEMO_SENSORS", "DEMO_TOOLS", "ENV_FLAG", "enabled", "with_demo_tools"]
