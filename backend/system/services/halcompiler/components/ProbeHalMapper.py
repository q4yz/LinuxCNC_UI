"""The `[probe]` component -> :class:`HalFragment` (`.agent/component/probe.md`).

One pin, one purpose: wire a touch-probe switch to LinuxCNC's own
`motion.probe-input` — a core motion pin, not a loadable component, so
there is no `loadrt` and no MCU-class gating to worry about (unlike
`[estop]`'s optional `iocontrol.0` enable chain, `motion.probe-input`
never collides with anything a motion-class router already owns).

Verified against the real, working reference machine,
`machine_config/example/PrintNC-WEBGUI/Machine.hal` (line 93):

    net probe-in  motion.probe-input <= parport.0.pin-15-in-not

This mapper emits the component-owned half directly (`net probe-in =>
motion.probe-input`) and a :class:`PinRequest` for the physical half;
the assembler's router pass appends the matching `net probe-in <=
parport.0.pin-15-in-not` (or the Remora/EtherCAT equivalent) — same
split-net pattern as every other component, and HAL's `net` command
lets a signal accumulate pins across separate statements the same way
the single combined line in the reference does.
"""

from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.hal_fragment_models import HalFragment, PinRequest, PinRole


class ProbeHalMapper:
    """The `[probe]` component's single digital-input wiring."""

    @staticmethod
    def to_fragment(probe: dict[str, Any] | None) -> HalFragment:
        fragment = HalFragment()
        if not probe:
            return fragment

        pin = probe.get("pin")
        if not pin:
            return fragment

        fragment.nets.append("net probe-in => motion.probe-input")
        fragment.requests.append(
            PinRequest(
                signal="probe-in",
                role=PinRole.DIGITAL_IN,
                pin=PinStringMapper.from_string(pin),
                owner="probe",
            )
        )
        return fragment


__all__ = ["ProbeHalMapper"]
