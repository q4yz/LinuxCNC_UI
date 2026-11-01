"""``[output_pin NAME]`` / ``[input_pin NAME]`` -> machine.hal
(`.agent/component/io_pins.md`; the webgui / halui half is
`IoPinWebguiMapper`).

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

from dataclasses import dataclass
from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.HalFragmentModels import (
    SERVO_THREAD,
    Addf,
    HalFragment,
    PinRequest,
    PinRole,
)

#: ``remora.SP.N`` is a duty in percent.
SP_FULL_SCALE = 100.0


@dataclass(frozen=True, slots=True)
class MdiCommand:
    """One ``[HALUI] MDI_COMMAND`` — ``halui.mdi-command-<index>``."""

    index: int
    input_id: str
    edge: str  # "rising" | "falling"
    subroutine: str
    gcode: str

    @property
    def ini_line(self) -> str:
        return f"MDI_COMMAND = o<{self.subroutine}> call"

    @property
    def file_name(self) -> str:
        return f"{self.subroutine}.ngc"

    @property
    def file_content(self) -> str:
        return (
            f"o<{self.subroutine}> sub\n{self.gcode}\no<{self.subroutine}> endsub\nM2\n"
        )


@dataclass(frozen=True, slots=True)
class HalpinSet:
    """``<edge>_halpin_set: <output>, <value>`` of one input."""

    input_id: str
    edge: str  # "rising" | "falling"
    output_id: str
    value: float

    @property
    def pulse(self) -> str:
        """The one-period signal of this input edge (`InputPinHalMapper`)."""
        return f"{self.input_id}-{self.edge}"


def halpin_sets(input_pins: list[dict[str, Any]]) -> list[HalpinSet]:
    """Every ``*_halpin_set`` entry, in declaration order (= latch order)."""
    return [
        HalpinSet(str(pin["id"]), edge, str(entry["output"]), float(entry["value"]))
        for pin in input_pins
        for edge in ("rising", "falling")
        for entry in pin.get(f"{edge}_halpin_set") or []
    ]


def latched_output_ids(input_pins: list[dict[str, Any]]) -> set[str]:
    return {s.output_id for s in halpin_sets(input_pins)}


def mdi_commands(input_pins: list[dict[str, Any]]) -> list[MdiCommand]:
    """Every input edge with G-code, in declaration order — the INI's
    ``MDI_COMMAND`` order is the ``halui.mdi-command-NN`` numbering, so
    the INI renderer and `IoPinWebguiMapper` both read this one list."""
    commands: list[MdiCommand] = []
    for pin in input_pins:
        for edge in ("rising", "falling"):
            gcode = pin.get(f"{edge}_ngc")
            if gcode:
                commands.append(
                    MdiCommand(len(commands), str(pin["id"]), edge, f"{pin['id']}_{edge}".lower(), str(gcode))
                )
    return commands


class OutputPinHalMapper:
    @staticmethod
    def to_fragment(output_pin: dict[str, Any], sets: list[HalpinSet] | None = None) -> HalFragment:
        """``sets``: the input edges targeting this output — it is then
        latched (`OutputLatchHalMapper`) instead of fed by webgui."""
        pin_id = str(output_pin["id"])
        pin = PinStringMapper.from_string(str(output_pin["pin"]))
        fragment = OutputLatchHalMapper.to_fragment(output_pin, sets) if sets else HalFragment()
        if not output_pin.get("pwm"):
            fragment.requests.append(
                PinRequest(signal=f"{pin_id}-out", role=PinRole.DIGITAL_OUT, pin=pin, owner=pin_id)
            )
            return fragment
        scale = f"{pin_id}-scale"
        gain = SP_FULL_SCALE / float(output_pin.get("scale") or 1.0)
        fragment.loadrt.append(f"loadrt scale names={scale}")
        fragment.addf.append(Addf(scale, SERVO_THREAD, order=1))
        fragment.setp.append(f"setp {scale}.gain {gain:g}")
        fragment.nets.append(f"net {pin_id}-SP <= {scale}.out")
        if sets:
            fragment.nets.append(f"net {pin_id}-latched => {scale}.in")
        fragment.requests.append(
            PinRequest(signal=f"{pin_id}-SP", role=PinRole.ANALOG_OUT, pin=pin, owner=pin_id)
        )
        return fragment


class OutputLatchHalMapper:
    """``<id>-latched`` = the value of the last event: a ``mux2`` chain
    fed back into its own start (a HAL signal keeps its value between
    cycles). Stage 0 is the UI (``webgui.<id>`` when ``webgui.<id>-set``
    toggles), then one stage per input edge (its ``HalpinSet.value``).
    A switched output is ``<id>-latched`` > 0.5."""

    @staticmethod
    def to_fragment(output_pin: dict[str, Any], sets: list[HalpinSet]) -> HalFragment:
        pin_id = str(output_pin["id"])
        ui_edge = f"{pin_id}-ui-edge"
        stages = [f"{pin_id}-set{k}" for k in range(len(sets) + 1)]
        outs = [f"{pin_id}-x{k}" for k in range(len(sets))] + [f"{pin_id}-latched"]
        fragment = HalFragment(
            loadrt=[f"loadrt edge names={ui_edge}", *(f"loadrt mux2 names={s}" for s in stages)],
            addf=[Addf(ui_edge, SERVO_THREAD, order=1), *(Addf(s, SERVO_THREAD, order=1) for s in stages)],
            setp=[f"setp {ui_edge}.both 1"],
            nets=[
                f"net {pin_id}-ui-pulse <= {ui_edge}.out => {stages[0]}.sel",
                f"net {pin_id}-latched => {stages[0]}.in0",
            ],
        )
        for k, (stage, out) in enumerate(zip(stages, outs)):
            fragment.nets.append(f"net {out} <= {stage}.out")
            if k:
                hal_set = sets[k - 1]
                fragment.setp.append(f"setp {stage}.in1 {hal_set.value:g}")
                fragment.nets.append(f"net {hal_set.pulse} => {stage}.sel")
                fragment.nets.append(f"net {outs[k - 1]} => {stage}.in0")
        if not output_pin.get("pwm"):
            on = f"{pin_id}-on"
            fragment.loadrt.append(f"loadrt comp names={on}")
            fragment.addf.append(Addf(on, SERVO_THREAD, order=1))
            fragment.setp.append(f"setp {on}.in0 0.5")
            fragment.nets.extend([f"net {pin_id}-latched => {on}.in1", f"net {pin_id}-out <= {on}.out"])
        return fragment


class InputPinHalMapper:
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
        # One pulse per edge that sets an output (``HalpinSet.pulse``).
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


__all__ = [
    "HalpinSet",
    "InputPinHalMapper",
    "MdiCommand",
    "OutputLatchHalMapper",
    "OutputPinHalMapper",
    "halpin_sets",
    "latched_output_ids",
    "mdi_commands",
]
