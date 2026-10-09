"""`[probe]` + `[tool_length_sensor]` -> :class:`HalFragment` (`.agent/component/probe.md`).

LinuxCNC has exactly one probe input, `motion.probe-input` (a core
motion pin — no `loadrt`). A machine can have two switches that should
trigger it: the touch probe and the tool-length sensor (tool setter).
Both are owned here because they share that one pin:

* only one declared  -> its signal drives `motion.probe-input` directly;
* both declared      -> an `or2` merges them, so either switch trips:

      loadrt or2 names=probe-or
      addf probe-or servo-thread
      net probe-in              => probe-or.in0
      net tool-length-sensor-in => probe-or.in1
      net probe-or-out probe-or.out => motion.probe-input

NC/NO is the pin's own `!` in the `.cfg`, handled per input by the MCU
router that binds the :class:`PinRequest` (`parport…-in-not`,
`remora.input.NN.not`, an explicit `not` stage for vfdmod) — so the
two switches can have opposite polarities and the OR always sees
"1 = triggered".

Verified against the real reference machine,
`machine_config/example/PrintNC-WEBGUI/Machine.hal` (line 93):

    net probe-in  motion.probe-input <= parport.0.pin-15-in-not
"""

from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.HalFragmentModels import (
    SERVO_THREAD,
    Addf,
    HalFragment,
    PinRequest,
    PinRole,
)

PROBE_SIGNAL = "probe-in"
TOOL_LENGTH_SENSOR_SIGNAL = "tool-length-sensor-in"
OR_NAME = "probe-or"
MOTION_PROBE_INPUT = "motion.probe-input"


class ProbeHalMapper:
    """Wires the probe and the tool-length sensor into `motion.probe-input`."""

    @staticmethod
    def to_fragment(
        probe: dict[str, Any] | None,
        tool_length_sensor: dict[str, Any] | None = None,
    ) -> HalFragment:
        fragment = HalFragment()
        inputs = [
            (signal, owner, pin)
            for signal, owner, record in (
                (PROBE_SIGNAL, "probe", probe),
                (TOOL_LENGTH_SENSOR_SIGNAL, "tool_length_sensor", tool_length_sensor),
            )
            if (pin := (record or {}).get("pin"))
        ]
        if not inputs:
            return fragment

        for signal, owner, pin in inputs:
            fragment.requests.append(
                PinRequest(
                    signal=signal,
                    role=PinRole.DIGITAL_IN,
                    pin=PinStringMapper.from_string(pin),
                    owner=owner,
                )
            )

        if len(inputs) == 1:
            signal = inputs[0][0]
            fragment.nets.append(f"net {signal} => {MOTION_PROBE_INPUT}")
            return fragment

        # Both switches: either one trips the probe input. The OR runs
        # with the input stage (order 0) — before motion reads it.
        fragment.loadrt.append(f"loadrt or2 names={OR_NAME}")
        fragment.addf.append(Addf(OR_NAME, SERVO_THREAD, order=0))
        for index, (signal, _owner, _pin) in enumerate(inputs):
            fragment.nets.append(f"net {signal} => {OR_NAME}.in{index}")
        fragment.nets.append(f"net probe-or-out {OR_NAME}.out => {MOTION_PROBE_INPUT}")
        return fragment


__all__ = ["ProbeHalMapper"]
