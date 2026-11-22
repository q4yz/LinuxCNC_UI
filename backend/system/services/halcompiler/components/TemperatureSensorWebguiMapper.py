"""A temperature sensor -> ``webgui_connections.hal``: the reading onto
``webgui.<id>`` (and a ``type: hal`` pin onto its signal)."""
from __future__ import annotations

from typing import Any

from .TemperatureSensorHalMapper import TemperatureSensorHalMapper


class TemperatureSensorWebguiMapper:
    """`webgui_connections.hal` side: the reading onto ``webgui.<id>``."""

    @staticmethod
    def to_lines(sensor: dict[str, Any]) -> list[str]:
        sensor_id = str(sensor["id"])
        lines = [f"# Temperature sensor: {sensor_id}"]
        pin = str(sensor.get("pin") or "")
        if TemperatureSensorHalMapper.is_hal_sensor(sensor) and "." in pin:
            lines.append(f"net {sensor_id}-PV <= {pin}")
        lines += [f"net {TemperatureSensorHalMapper.sensor_signal(sensor)} => webgui.{sensor_id}", ""]
        return lines


__all__ = ["TemperatureSensorWebguiMapper"]
