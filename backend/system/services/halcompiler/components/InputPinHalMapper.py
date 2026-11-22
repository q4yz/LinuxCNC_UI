"""``[output_pin NAME]`` / ``[input_pin NAME]`` -> machine.hal
(`.agent/component/io_pins.md`; the webgui / halui half is
`InputPinWebguiMapper`).

* Switched output: a digital output fed by ``<id>-out`` (``webgui.<id>``,
  a bit).
* PWM output: an analog output (``remora.SP.N``, 0 ... 100 %) fed by a
  ``scale`` from ``webgui.<id>`` in the profile's ``scale`` units.
* Input: a digital input ``<id>-in``. Its ``rising_ngc`` /
  ``falling_ngc`` run as halui MDI commands (``o<sub> call`` of a
  generated subroutine, `mdi_commands`); the falling edge goes through a
  ``not`` because an MDI command fires on a rising pin.
* ``rising_halpin_set`` / ``falling_halpin_set``: an input edge sets one of
  the profile's own outputs to a value, in realtime HAL (no MDI, works
  while a program runs). HAL allows one writer per signal, so such a
  target output is latched (`OutputLatchHalMapper`): every event — an
  input edge, or the UI toggling ``webgui.<id>-set`` — puts its value
  into ``<id>-latched``; the last one wins.
"""
from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.HalFragmentModels import SERVO_THREAD, Addf, HalFragment, PinRequest, PinRole
from models.machineconfig.InputPinActionModels import HalpinSetAction, MdiCommand


class InputPinHalMapper:
    @staticmethod
    def halpin_sets(input_pins: list[dict[str, Any]]) -> list[HalpinSetAction]:
        """Every ``*_halpin_set`` entry, in declaration order (= latch order)."""
        return [
            HalpinSetAction(str(pin["id"]), edge, str(entry["output"]), float(entry["value"]))
            for pin in input_pins
            for edge in ("rising", "falling")
            for entry in pin.get(f"{edge}_halpin_set") or []
        ]


    @staticmethod
    def latched_output_ids(input_pins: list[dict[str, Any]]) -> set[str]:
        return {s.output_id for s in InputPinHalMapper.halpin_sets(input_pins)}


    @staticmethod
    def mdi_commands(input_pins: list[dict[str, Any]]) -> list[MdiCommand]:
        """Every input edge with G-code, in declaration order — the INI's
        ``MDI_COMMAND`` order is the ``halui.mdi-command-NN`` numbering, so
        the INI renderer and `InputPinWebguiMapper` both read this one list."""
        commands: list[MdiCommand] = []
        for pin in input_pins:
            for edge in ("rising", "falling"):
                gcode = pin.get(f"{edge}_ngc")
                if gcode:
                    commands.append(
                        MdiCommand(len(commands), str(pin["id"]), edge, f"{pin['id']}_{edge}".lower(), str(gcode))
                    )
        return commands

    @staticmethod
    def to_fragment(input_pin: dict[str, Any]) -> HalFragment:
        pin_id = str(input_pin["id"])
        fragment = HalFragment(
            requests=[
                PinRequest(
                    signal=f"{pin_id}-in",
                    role=PinRole.DIGITAL_IN,
                    pin=PinStringMapper.from_string(str(input_pin["pin"])),
                    owner=pin_id,
                )
            ]
        )
        if input_pin.get("falling_ngc"):
            released = f"{pin_id}-released"
            fragment.loadrt.append(f"loadrt not names={released}")
            fragment.addf.append(Addf(released, SERVO_THREAD, order=1))
            fragment.nets.append(f"net {pin_id}-in => {released}.in")
        # One pulse per edge that sets an output (``HalpinSetAction.pulse``).
        for edge in ("rising", "falling"):
            if not input_pin.get(f"{edge}_halpin_set"):
                continue
            detector = f"{pin_id}-{edge}-edge"
            fragment.loadrt.append(f"loadrt edge names={detector}")
            fragment.addf.append(Addf(detector, SERVO_THREAD, order=1))
            if edge == "falling":
                fragment.setp.append(f"setp {detector}.in-edge 0")
            fragment.nets.extend([f"net {pin_id}-in => {detector}.in", f"net {pin_id}-{edge} <= {detector}.out"])
        return fragment


__all__ = ["InputPinHalMapper"]
