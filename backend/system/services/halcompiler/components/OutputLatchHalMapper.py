"""An output that input edges set too (``<edge>_halpin_set``): one writer
per HAL signal, so it is latched — see :class:`OutputLatchHalMapper`."""
from __future__ import annotations

from typing import Any

from models.machineconfig.HalFragmentModels import SERVO_THREAD, Addf, HalFragment
from models.machineconfig.InputPinActionModels import HalpinSetAction


class OutputLatchHalMapper:
    """``<id>-latched`` = the value of the last event: a ``mux2`` chain
    fed back into its own start (a HAL signal keeps its value between
    cycles). Stage 0 is the UI (``webgui.<id>`` when ``webgui.<id>-set``
    toggles), then one stage per input edge (its ``HalpinSetAction.value``).
    A switched output is ``<id>-latched`` > 0.5."""

    @staticmethod
    def to_fragment(output_pin: dict[str, Any], sets: list[HalpinSetAction]) -> HalFragment:
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


__all__ = ["OutputLatchHalMapper"]
