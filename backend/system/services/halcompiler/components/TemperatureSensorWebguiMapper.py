"""A temperature sensor -> ``webgui_connections.hal``: the reading onto
``webgui.<id>`` (and a ``type: hal`` pin onto its signal)."""
from __future__ import annotations

from models.machineconfig.HardwareJsonModels import TemperatureSensor

from .TemperatureSensorHalMapper import TemperatureSensorHalMapper


class TemperatureSensorWebguiMapper:
    """`webgui_connections.hal` side: the reading onto ``webgui.<id>``."""

    @staticmethod
    def to_lines(sensor: TemperatureSensor) -> list[str]:
        sensor_id = sensor.id
        lines = [f"# Temperature sensor: {sensor_id}"]
        if TemperatureSensorHalMapper.is_hal_sensor(sensor.type) and "." in sensor.pin:
            lines.append(f"net {sensor_id}-PV <= {sensor.pin}")
        lines += [f"net {TemperatureSensorHalMapper.sensor_signal(sensor)} => webgui.{sensor_id}", ""]
        return lines


__all__ = ["TemperatureSensorWebguiMapper"]
