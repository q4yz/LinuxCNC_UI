"""A temperature sensor no heater reads -> :class:`HalFragment` and
its `webgui_connections.hal` binding (`.agent/component/temperature_sensor.md`).

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
  :func:`hal_pin_diagnostics` refuses a pin nothing loads or the
  generated HAL already wires.
"""

from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.DiagnosticModels import Diagnostic, Severity
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


def sensor_kind(sensor: dict[str, Any]) -> str:
    """``hal`` / ``temperature_host`` / ``temperature_mcu``, or
    ``thermistor`` for a board pin."""
    kind = str(sensor.get("type") or "").strip().lower()
    return kind if kind in (HAL, HOST, MCU) else "thermistor"


def is_hal_sensor(sensor: dict[str, Any]) -> bool:
    """``type: hal`` — ``pin`` is a HAL name, not a board pin."""
    return sensor_kind(sensor) == HAL


def is_board_sensor(sensor: dict[str, Any]) -> bool:
    """A thermistor on a board pin — the only kind whose ``pin`` is one."""
    return sensor_kind(sensor) == "thermistor"


def sensor_signal(sensor: dict[str, Any]) -> str:
    """The HAL signal carrying the reading: the operator's own signal for
    ``type: hal`` with no dot, ``<id>-PV`` otherwise."""
    pin = str(sensor.get("pin") or "")
    if is_hal_sensor(sensor) and "." not in pin:
        return pin
    return f"{sensor['id']}-PV"


def host_load_line(sensor: dict[str, Any]) -> str:
    """``loadusr -Wn rpi-monitor ...`` for a ``temperature_host`` sensor;
    ``thermal_zone`` pins the zone (the component's own default is zone
    0, which on the BTT CB1 is the GPU, not the CPU)."""
    zone = sensor.get("thermal_zone")
    env = f"env RPI_MONITOR_TEMP_FILE=/sys/class/thermal/thermal_zone{int(zone)}/temp " if zone is not None else ""
    return f"loadusr -Wn rpi-monitor {env}{RPI_MONITOR_COMMAND}"


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


#: Pin prefixes LinuxCNC provides without a ``loadrt`` / ``loadusr`` in
#: the machine's HAL files (motion controller, I/O controller, halui).
_CORE_COMPONENTS = frozenset({"motion", "joint", "axis", "spindle", "iocontrol", "halui", "ini"})
#: Drivers whose pins are not named after the module.
_DRIVER_PREFIXES = {"remora-spi": "remora", "remora_lpc": "remora", "remora-eth-3.0": "remora"}


def _hal_commands(text: str) -> list[list[str]]:
    """Every HAL command line's words, comments dropped."""
    return [line.split("#", 1)[0].split() for line in text.splitlines() if line.split("#", 1)[0].strip()]


def loaded_components(hal_text: str) -> set[str]:
    """Component names (= pin prefixes) a HAL file's ``loadrt`` /
    ``loadusr`` lines create."""
    names: set[str] = set()
    for words in _hal_commands(hal_text):
        if words[0] == "loadrt" and len(words) > 1:
            module = words[1]
            given = [w.split("=", 1)[1] for w in words[2:] if w.startswith("names=")]
            names.update(n for g in given for n in g.split(",") if n)
            if not given:
                names.add(_DRIVER_PREFIXES.get(module, module))
        elif words[0] == "loadusr":
            rest = words[1:]
            for i, word in enumerate(rest):
                if word.startswith("-") and "n" in word[1:] and i + 1 < len(rest):
                    names.add(rest[i + 1])
                    break
            else:
                program = next((w for w in rest if not w.startswith("-") and "=" not in w and w != "env"), None)
                if program:
                    names.add(program.rsplit("/", 1)[-1])
    return names


def hal_pin_diagnostics(payload: dict[str, Any], machine_hal: str, user_hal: str = "") -> list[Diagnostic]:
    """``type: hal`` pins LinuxCNC would abort on, found before it starts:

    * ``E_HAL_PIN_NO_COMPONENT`` — nothing creates the pin: neither the
      generated ``machine.hal``, LinuxCNC itself nor ``user.hal`` loads
      its component;
    * ``E_HAL_PIN_IN_USE`` — the pin is already on a signal (generated
      wiring, ``user.hal``, or another sensor) — a HAL pin sits on one
      signal only.
    """
    found: list[Diagnostic] = []
    components = loaded_components(machine_hal) | loaded_components(user_hal) | _CORE_COMPONENTS
    wired: dict[str, str] = {}
    for source, text in (("the generated machine.hal", machine_hal), ("user.hal", user_hal)):
        for words in _hal_commands(text):
            if words[0] == "net":
                for word in words[2:]:
                    wired.setdefault(word, source)
    for sensor in unclaimed_sensors(payload):
        pin = str(sensor.get("pin") or "")
        if not is_hal_sensor(sensor) or "." not in pin:
            continue
        owner = str(sensor["id"])
        prefix = pin.split(".", 1)[0]
        if prefix not in components:
            found.append(Diagnostic(
                "E_HAL_PIN_NO_COMPONENT", Severity.ERROR,
                f"sensor_pin {pin!r}: nothing loads the {prefix!r} component, so the pin does not "
                f"exist. Load it in user.hal (kept across regenerations), or use sensor_type: "
                f"temperature_host for the host CPU / temperature_mcu for the board's MCU.",
                owner,
            ))
        if pin in wired:
            found.append(Diagnostic(
                "E_HAL_PIN_IN_USE", Severity.ERROR,
                f"sensor_pin {pin!r} is already wired in {wired[pin]}; a HAL pin sits on one signal "
                f"only. Give the signal's name instead (no dot), or pick another pin.",
                owner,
            ))
        wired.setdefault(pin, f"temperature_sensor {owner}")
    return found


class TemperatureSensorHalMapper:
    """`machine.hal` side: where the reading comes from."""

    @staticmethod
    def to_fragment(sensor: dict[str, Any]) -> HalFragment:
        fragment = HalFragment()
        sensor_id = str(sensor["id"])
        pin = str(sensor["pin"])
        kind = sensor_kind(sensor)
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
            fragment.loadusr.append(host_load_line(sensor))
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


class TemperatureSensorWebguiMapper:
    """`webgui_connections.hal` side: the reading onto ``webgui.<id>``."""

    @staticmethod
    def to_lines(sensor: dict[str, Any]) -> list[str]:
        sensor_id = str(sensor["id"])
        lines = [f"# Temperature sensor: {sensor_id}"]
        pin = str(sensor.get("pin") or "")
        if is_hal_sensor(sensor) and "." in pin:
            lines.append(f"net {sensor_id}-PV <= {pin}")
        lines += [f"net {sensor_signal(sensor)} => webgui.{sensor_id}", ""]
        return lines


__all__ = [
    "TemperatureSensorHalMapper",
    "TemperatureSensorWebguiMapper",
    "HAL",
    "HOST",
    "MCU",
    "hal_pin_diagnostics",
    "host_load_line",
    "loaded_components",
    "is_board_sensor",
    "is_hal_sensor",
    "sensor_kind",
    "sensor_signal",
    "unclaimed_sensors",
]
