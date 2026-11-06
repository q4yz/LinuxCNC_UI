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

Two HAL pins the compiler knows how to provide, so the machine starts
without hand edits:

* ``remora.mcu-temp`` — the Remora board's own MCU temperature: an
  ``ANALOG_IN`` request the Remora router turns into a free
  ``remora.PV.N``, the firmware's "MCU Temperature" module and an
  ``alias pin`` to this name;
* ``rpi-monitor.*`` — the host's CPU temperature/load: one
  ``loadusr -Wn rpi-monitor`` line (the component `install.sh` puts on
  ``PATH``). Any other HAL pin's component is the operator's to load.
"""

from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.HalFragmentModels import HalFragment, PinRequest, PinRole
from models.machineconfig.PinModels import ParsedPin

from ..mcus.RemoraRouterMapper import MCU_TEMP_PIN, MCU_TEMP_SENSOR_TYPE

#: The host monitor's HAL component (Remora-m8p
#: ``LinuxCNC/Components/RPiMonitor``), installed as
#: ``/usr/local/bin/rpi-monitor`` by ``scripts/install_hal_components.sh``.
RPI_MONITOR_PREFIX = "rpi-monitor."
RPI_MONITOR_LOAD = "loadusr -Wn rpi-monitor python3 /usr/local/bin/rpi-monitor 1.0"


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


def is_mcu_temp_sensor(sensor: dict[str, Any]) -> bool:
    """``type: hal`` reading ``remora.mcu-temp``."""
    return is_hal_sensor(sensor) and str(sensor.get("pin") or "").strip() == MCU_TEMP_PIN


def remora_mcu_id(payload: dict[str, Any]) -> str | None:
    """The ``remora-spi`` board (not a CAN node) — the one ``remora.*``
    pins belong to, or ``None``."""
    for mcu in payload.get("mcus") or []:
        if isinstance(mcu, dict) and mcu.get("connection") == "remora-spi":
            return str(mcu["id"])
    return None


def component_loads(sensors: list[dict[str, Any]]) -> list[str]:
    """``loadusr`` lines for the components the sensors' HAL pins need,
    each once."""
    if any(is_hal_sensor(s) and str(s.get("pin") or "").startswith(RPI_MONITOR_PREFIX) for s in sensors):
        return [RPI_MONITOR_LOAD]
    return []


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
    def to_fragment(sensor: dict[str, Any], remora_id: str | None = None) -> HalFragment:
        fragment = HalFragment()
        sensor_id = str(sensor["id"])
        pin = str(sensor["pin"])
        if is_mcu_temp_sensor(sensor) and remora_id is not None:
            fragment.requests.append(
                PinRequest(
                    signal=f"{sensor_id}-PV",
                    role=PinRole.ANALOG_IN,
                    pin=ParsedPin(raw=pin, mcu_id=remora_id, pin_id="mcu-temp"),
                    owner=sensor_id,
                    sensor_type=MCU_TEMP_SENSOR_TYPE,
                )
            )
            return fragment
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
    "component_loads",
    "is_hal_sensor",
    "is_mcu_temp_sensor",
    "remora_mcu_id",
    "sensor_signal",
    "unclaimed_sensors",
]
