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

from mappers.machineconfig import PinStringMapper
from models.machineconfig.HalFragmentModels import SERVO_THREAD, Addf, HalFragment, PinRequest, PinRole
from models.machineconfig.HardwareJsonModels import HalpinSet as HardwareHalpinSet, InputPin
from models.machineconfig.InputPinActionModels import HalpinSetAction, MdiCommand


class InputPinHalMapper:
    @staticmethod
    def halpin_set(pin: InputPin, edge: str) -> list[HardwareHalpinSet]:
        return pin.rising_halpin_set if edge == "rising" else pin.falling_halpin_set

    @staticmethod
    def halpin_sets(input_pins: list[InputPin]) -> list[HalpinSetAction]:
        """Every ``*_halpin_set`` entry, in declaration order (= latch order)."""
        return [
            HalpinSetAction(pin.id, edge, entry.output, entry.value)
            for pin in input_pins
            for edge in ("rising", "falling")
            for entry in InputPinHalMapper.halpin_set(pin, edge)
        ]

    @staticmethod
    def latched_output_ids(input_pins: list[InputPin]) -> set[str]:
        return {s.output_id for s in InputPinHalMapper.halpin_sets(input_pins)}

    @staticmethod
    def mdi_commands(input_pins: list[InputPin]) -> list[MdiCommand]:
        """Every input edge with G-code, in declaration order — the INI's
        ``MDI_COMMAND`` order is the ``halui.mdi-command-NN`` numbering, so
        the INI renderer and `InputPinWebguiMapper` both read this one list."""
        commands: list[MdiCommand] = []
        for pin in input_pins:
            for edge in ("rising", "falling"):
                gcode = pin.rising_ngc if edge == "rising" else pin.falling_ngc
                if gcode:
                    commands.append(MdiCommand(len(commands), pin.id, edge, f"{pin.id}_{edge}".lower(), gcode))
        return commands

    @staticmethod
    def to_fragment(input_pin: InputPin) -> HalFragment:
        pin_id = input_pin.id
        fragment = HalFragment(
            requests=[
                PinRequest(
                    signal=f"{pin_id}-in",
                    role=PinRole.DIGITAL_IN,
                    pin=PinStringMapper.from_string(input_pin.pin),
                    owner=pin_id,
                )
            ]
        )
        if input_pin.falling_ngc:
            released = f"{pin_id}-released"
            fragment.loadrt.append(f"loadrt not names={released}")
            fragment.addf.append(Addf(released, SERVO_THREAD, order=1))
            fragment.nets.append(f"net {pin_id}-in => {released}.in")
        # One pulse per edge that sets an output (``HalpinSetAction.pulse``).
        for edge in ("rising", "falling"):
            if not InputPinHalMapper.halpin_set(input_pin, edge):
                continue
            detector = f"{pin_id}-{edge}-edge"
            fragment.loadrt.append(f"loadrt edge names={detector}")
            fragment.addf.append(Addf(detector, SERVO_THREAD, order=1))
            if edge == "falling":
                fragment.setp.append(f"setp {detector}.in-edge 0")
            fragment.nets.extend([f"net {pin_id}-in => {detector}.in", f"net {pin_id}-{edge} <= {detector}.out"])
        return fragment


__all__ = ["InputPinHalMapper"]
