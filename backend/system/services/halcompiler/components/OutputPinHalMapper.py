"""``[output_pin NAME]`` -> machine.hal (`.agent/component/io_pins.md`;
the webgui half is `OutputPinWebguiMapper`).

* Switched output: a digital output fed by ``<id>-out`` (``webgui.<id>``, a bit).
* PWM output: an analog output (``remora.SP.N``, 0 ... 100 %) fed by a
  ``scale`` from ``webgui.<id>`` in the profile's ``scale`` units.
* Set by input edges too: latched (`OutputLatchHalMapper`).
"""
from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.HalFragmentModels import SERVO_THREAD, Addf, HalFragment, PinRequest, PinRole
from models.machineconfig.InputPinActionModels import HalpinSetAction

from .OutputLatchHalMapper import OutputLatchHalMapper

#: ``remora.SP.N`` is a duty in percent.
SP_FULL_SCALE = 100.0


class OutputPinHalMapper:
    @staticmethod
    def to_fragment(output_pin: dict[str, Any], sets: list[HalpinSetAction] | None = None) -> HalFragment:
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


__all__ = ["OutputPinHalMapper", "SP_FULL_SCALE"]
