"""``type: hal`` temperature sensor pins against the generated HAL: the
checks that need ``machine.hal`` / ``user.hal`` text, so they run after
assembly (:func:`compile_machine_hal`), unlike :class:`MachineValidator`."""
from __future__ import annotations

from typing import Any

from models.machineconfig.DiagnosticModels import Diagnostic, Severity

from .components.TemperatureSensorHalMapper import TemperatureSensorHalMapper

#: Pin prefixes LinuxCNC provides without a ``loadrt`` / ``loadusr`` in
#: the machine's HAL files (motion controller, I/O controller, halui).
_CORE_COMPONENTS = frozenset({"motion", "joint", "axis", "spindle", "iocontrol", "halui", "ini"})
#: Drivers whose pins are not named after the module.
_DRIVER_PREFIXES = {"remora-spi": "remora", "remora_lpc": "remora", "remora-eth-3.0": "remora"}


class HalPinValidator:
    @staticmethod
    def _hal_commands(text: str) -> list[list[str]]:
        """Every HAL command line's words, comments dropped."""
        return [line.split("#", 1)[0].split() for line in text.splitlines() if line.split("#", 1)[0].strip()]


    @staticmethod
    def loaded_components(hal_text: str) -> set[str]:
        """Component names (= pin prefixes) a HAL file's ``loadrt`` /
        ``loadusr`` lines create."""
        names: set[str] = set()
        for words in HalPinValidator._hal_commands(hal_text):
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


    @staticmethod
    def diagnostics(payload: dict[str, Any], machine_hal: str, user_hal: str = "") -> list[Diagnostic]:
        """``type: hal`` pins LinuxCNC would abort on, found before it starts:

        * ``E_HAL_PIN_NO_COMPONENT`` — nothing creates the pin: neither the
          generated ``machine.hal``, LinuxCNC itself nor ``user.hal`` loads
          its component;
        * ``E_HAL_PIN_IN_USE`` — the pin is already on a signal (generated
          wiring, ``user.hal``, or another sensor) — a HAL pin sits on one
          signal only.
        """
        found: list[Diagnostic] = []
        components = HalPinValidator.loaded_components(machine_hal) | HalPinValidator.loaded_components(user_hal) | _CORE_COMPONENTS
        wired: dict[str, str] = {}
        for source, text in (("the generated machine.hal", machine_hal), ("user.hal", user_hal)):
            for words in HalPinValidator._hal_commands(text):
                if words[0] == "net":
                    for word in words[2:]:
                        wired.setdefault(word, source)
        for sensor in TemperatureSensorHalMapper.unclaimed_sensors(payload):
            pin = sensor.pin
            if not TemperatureSensorHalMapper.is_hal_sensor(sensor.type) or "." not in pin:
                continue
            owner = sensor.id
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


__all__ = ["HalPinValidator"]
