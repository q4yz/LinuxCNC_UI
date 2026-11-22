"""A temperature sensor no heater reads -> :class:`HalFragment` and
its `webgui_connections.hal` binding (`TemperatureSensorWebguiMapper`; `.agent/component/temperature_sensor.md`).

A heater's own sensor is wired by `HeaterHalMapper` (the loop reads its
``<id>-PV``) and bound by `HeaterWebguiMapper`; this covers every other
``temperature_sensors[]`` record, so it still reaches the temperature plot:

* a thermistor on a board pin — an ``ANALOG_IN`` request for
  ``<id>-PV``, routed by the MCU like a heater's sensor;
* ``type: temperature_mcu`` — an ``ANALOG_IN`` request the Remora router
  turns into the next free ``remora.PV.N`` plus the firmware's
  "MCU Temperature" module;
* ``type: temperature_host`` — ``machine.hal`` loads ``rpi-monitor``
  (once) and reads its ``cpu-temp`` pin;
* ``type: hal`` — any float HAL pin (has a dot) or existing signal (no
  dot). Its ``net`` goes into ``webgui_connections.hal``, not
  ``machine.hal``: that file runs after ``user.hal``, so the pin may
  belong to a component the operator loads there.
  :class:`HalPinValidator` refuses a pin nothing loads or the
  generated HAL already wires.
"""

from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.HalFragmentModels import HalFragment, PinRequest, PinRole
from models.machineconfig.PinModels import ParsedPin

from ..mcus.RemoraRouterMapper import MCU_TEMP_SENSOR_TYPE

HAL = "hal"
HOST = "temperature_host"
MCU = "temperature_mcu"

#: The host monitor's HAL component (Remora-m8p
#: ``LinuxCNC/Components/RPiMonitor``), installed as
#: ``/usr/local/bin/rpi-monitor`` by ``scripts/install_hal_components.sh``.
RPI_MONITOR_COMMAND = "python3 /usr/local/bin/rpi-monitor 1.0"


class TemperatureSensorHalMapper:
    """`machine.hal` side: where the reading comes from."""

    @staticmethod
    def sensor_kind(sensor: dict[str, Any]) -> str:
        """``hal`` / ``temperature_host`` / ``temperature_mcu``, or
        ``thermistor`` for a board pin."""
        kind = str(sensor.get("type") or "").strip().lower()
        return kind if kind in (HAL, HOST, MCU) else "thermistor"


    @staticmethod
    def is_hal_sensor(sensor: dict[str, Any]) -> bool:
        """``type: hal`` — ``pin`` is a HAL name, not a board pin."""
        return TemperatureSensorHalMapper.sensor_kind(sensor) == HAL


    @staticmethod
    def is_board_sensor(sensor: dict[str, Any]) -> bool:
        """A thermistor on a board pin — the only kind whose ``pin`` is one."""
        return TemperatureSensorHalMapper.sensor_kind(sensor) == "thermistor"


    @staticmethod
    def sensor_signal(sensor: dict[str, Any]) -> str:
        """The HAL signal carrying the reading: the operator's own signal for
        ``type: hal`` with no dot, ``<id>-PV`` otherwise."""
        pin = str(sensor.get("pin") or "")
        if TemperatureSensorHalMapper.is_hal_sensor(sensor) and "." not in pin:
            return pin
        return f"{sensor['id']}-PV"


    @staticmethod
    def host_load_line(sensor: dict[str, Any]) -> str:
        """``loadusr -Wn rpi-monitor ...`` for a ``temperature_host`` sensor;
        ``thermal_zone`` pins the zone (the component's own default is zone
        0, which on the BTT CB1 is the GPU, not the CPU)."""
        zone = sensor.get("thermal_zone")
        env = f"env RPI_MONITOR_TEMP_FILE=/sys/class/thermal/thermal_zone{int(zone)}/temp " if zone is not None else ""
        return f"loadusr -Wn rpi-monitor {env}{RPI_MONITOR_COMMAND}"


    @staticmethod
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

    @staticmethod
    def to_fragment(sensor: dict[str, Any]) -> HalFragment:
        fragment = HalFragment()
        sensor_id = str(sensor["id"])
        pin = str(sensor["pin"])
        kind = TemperatureSensorHalMapper.sensor_kind(sensor)
        if kind == MCU:
            # ``pin`` is the Remora board's MCU id (hardware_json_generator).
            fragment.requests.append(
                PinRequest(
                    signal=f"{sensor_id}-PV",
                    role=PinRole.ANALOG_IN,
                    pin=ParsedPin(raw=pin, mcu_id=pin, pin_id="mcu-temp"),
                    owner=sensor_id,
                    sensor_type=MCU_TEMP_SENSOR_TYPE,
                )
            )
            return fragment
        if kind == HOST:
            fragment.loadusr.append(TemperatureSensorHalMapper.host_load_line(sensor))
            fragment.nets.append(f"net {sensor_id}-PV <= {pin}")
            return fragment
        if kind == HAL:
            return fragment  # wired in webgui_connections.hal, see module docstring
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


__all__ = ["HAL", "HOST", "MCU", "RPI_MONITOR_COMMAND", "TemperatureSensorHalMapper"]
