"""A temperature sensor no heater reads -> :class:`HalFragment` and
its `webgui_connections.hal` binding (`.agent/component/temperature_sensor.md`).

A heater's own sensor is wired by `HeaterHalMapper` (the loop reads its
``<id>-PV``) and bound by `HeaterWebguiMapper`; this covers every other
``temperature_sensors[]`` record, so it still reaches the temperature plot:

* a thermistor on a board pin — an ``ANALOG_IN`` request for
  ``<id>-PV``, routed by the MCU like a heater's sensor;
* ``type: hal`` with a HAL **pin** (has a dot, ``rpi-monitor.cpu-temp``)
  — ``net <id>-PV <= <pin>``;
* ``type: hal`` with a HAL **signal** (no dot, ``cpu-temp``) — nothing
  in ``machine.hal``: the operator's own HAL already drives it, and a
  pin sits on one signal only, so the UI just becomes another reader.

The component behind a HAL pin is never loaded here — that stays in the
operator's own HAL file (``loadusr -Wn rpi-monitor ...``).
"""

from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.HalFragmentModels import HalFragment, PinRequest, PinRole


def is_hal_sensor(sensor: dict[str, Any]) -> bool:
    """``type: hal`` — ``pin`` is a HAL name, not a board pin."""
    return str(sensor.get("type") or "").strip().lower() == "hal"


def sensor_signal(sensor: dict[str, Any]) -> str:
    """The HAL signal carrying the reading: the operator's own signal for
    ``type: hal`` with no dot, ``<id>-PV`` otherwise."""
    pin = str(sensor.get("pin") or "")
    if is_hal_sensor(sensor) and "." not in pin:
        return pin
    return f"{sensor['id']}-PV"


def unclaimed_sensors(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """``temperature_sensors[]`` no ``tools[].sensor`` references."""
    claimed = {
        t.get("sensor") for t in payload.get("tools") or [] if isinstance(t, dict)
    }
    return [
        s
        for s in payload.get("temperature_sensors") or []
        if isinstance(s, dict) and s.get("id") and s.get("pin") and s["id"] not in claimed
    ]


class TemperatureSensorHalMapper:
    """`machine.hal` side: where the reading comes from."""

    @staticmethod
    def to_fragment(sensor: dict[str, Any]) -> HalFragment:
        fragment = HalFragment()
        sensor_id = str(sensor["id"])
        pin = str(sensor["pin"])
        if is_hal_sensor(sensor):
            if "." in pin:
                fragment.nets.append(f"net {sensor_id}-PV <= {pin}")
            return fragment
        fragment.requests.append(
            PinRequest(
                signal=f"{sensor_id}-PV",
                role=PinRole.ANALOG_IN,
                pin=PinStringMapper.from_string(pin),
                owner=sensor_id,
                sensor_type=sensor.get("type"),
            )
        )
        return fragment


class TemperatureSensorWebguiMapper:
    """`webgui_connections.hal` side: the reading onto ``webgui.<id>``."""

    @staticmethod
    def to_lines(sensor: dict[str, Any]) -> list[str]:
        sensor_id = str(sensor["id"])
        return [
            f"# Temperature sensor: {sensor_id}",
            f"net {sensor_signal(sensor)} => webgui.{sensor_id}",
            "",
        ]


__all__ = [
    "TemperatureSensorHalMapper",
    "TemperatureSensorWebguiMapper",
    "is_hal_sensor",
    "sensor_signal",
    "unclaimed_sensors",
]
