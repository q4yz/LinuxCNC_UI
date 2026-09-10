"""The `[estop]` component -> :class:`HalFragment` (`.agent/component/estop.md`).

Two independent halves, matching the two things `[estop]` can carry:

* **UI pulse chain (unconditional).** `StateService.activate_estop()`
  just asserts the webgui `estop` pin (`webgui.estop`,
  `common/dtos/EStopDto.py`) `True` and leaves it there — a
  *continuous* level, not a pulse. `halui.estop.activate` needs a
  *rising edge* every time the operator presses the button, not a
  held level, so a `oneshot` turns the continuous UI signal into a
  0.1 s pulse before it reaches halui. This half needs no hardware at
  all — it is what makes an empty `[estop]` block useful on its own
  for a UI-only machine.

* **Physical E-stop chain (optional, per pin).** `fault_pin`/`out_pin`
  mirror the hand-wired chain in the real reference machine,
  `machine_config/example/PrintNC-WEBGUI/Machine.hal` (lines 41-57):
  an `estop_latch` gates LinuxCNC's own enable state on a physical
  fault input, and a physical output pin mirrors LinuxCNC's enable
  state back out (a lamp, a relay, a second machine's E-stop loop).
  Each pin is independently optional.

  This half is skipped on a class-B (Remora/EtherCAT) MCU: that
  router's own `base_fragment()` already nets `iocontrol.0.
  user-enable-out` / `user-request-enable` / `emc-enable-in` for its
  own SPI/EtherCAT link-health chain (`RemoraRouterMapper.
  base_fragment`) — wiring `estop_latch` on top of the *same* pins
  would double-drive them, a genuine HAL load error, not a cosmetic
  one. The physical pin itself is still routed (a `PinRequest`
  survives either way, so a Remora `fault_pin` still becomes a real
  `config.txt` "Digital Pin" module) — only the `iocontrol`/
  `estop_latch` linkage is skipped, and only on the MCU that pin
  actually targets, never the whole machine.
"""

from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.hal_fragment_models import (
    SERVO_THREAD,
    Addf,
    HalFragment,
    PinRequest,
    PinRole,
)
from models.machineconfig.pin_models import CapabilityClass

#: `oneshot`'s pulse width in seconds. Long enough for halui to
#: register the rising edge every servo cycle, short enough nothing
#: reads it as "held" — the worked example's own 100 ms.
_PULSE_WIDTH_SECONDS = 0.1

_ONESHOT = "estop-pulse-generator"


class EstopHalMapper:
    """The `[estop]` component — UI pulse chain plus optional hardware."""

    @staticmethod
    def to_fragment(
        estop: dict[str, Any], mcus_by_id: dict[str, dict[str, Any]]
    ) -> HalFragment:
        fragment = HalFragment(
            loadrt=[f"loadrt oneshot names={_ONESHOT}"],
            addf=[Addf(_ONESHOT, SERVO_THREAD, order=1)],
            setp=[f"setp {_ONESHOT}.width {_PULSE_WIDTH_SECONDS}"],
            nets=[
                f"net continuous-estop-in webgui.estop => {_ONESHOT}.in",
                f"net pulsed-estop-out {_ONESHOT}.out => halui.estop.activate",
            ],
        )

        fault_pin = estop.get("fault_pin")
        if fault_pin:
            EstopHalMapper._fault_chain(fragment, fault_pin, mcus_by_id)

        out_pin = estop.get("out_pin")
        if out_pin:
            EstopHalMapper._out_chain(fragment, out_pin, mcus_by_id)

        return fragment

    # -- physical chain ----------------------------------------------------- #

    @staticmethod
    def _fault_chain(
        fragment: HalFragment, fault_pin: str, mcus_by_id: dict[str, dict[str, Any]]
    ) -> None:
        fragment.requests.append(
            PinRequest(
                signal="estop-fault",
                role=PinRole.DIGITAL_IN,
                pin=PinStringMapper.from_string(fault_pin),
                owner="estop",
            )
        )
        if not EstopHalMapper._owns_iocontrol_chain(fault_pin, mcus_by_id):
            return
        fragment.loadrt.append("loadrt estop_latch")
        fragment.addf.append(Addf("estop-latch.0", SERVO_THREAD, order=1))
        fragment.nets.extend(
            [
                "net estop-fault => estop-latch.0.fault-in",
                "net estop-reset <= iocontrol.0.user-request-enable",
                "net estop-reset => estop-latch.0.reset",
                "net estop-ext <= estop-latch.0.ok-out",
                "net estop-ext => iocontrol.0.emc-enable-in",
            ]
        )

    @staticmethod
    def _out_chain(
        fragment: HalFragment, out_pin: str, mcus_by_id: dict[str, dict[str, Any]]
    ) -> None:
        fragment.requests.append(
            PinRequest(
                signal="estop-out",
                role=PinRole.DIGITAL_OUT,
                pin=PinStringMapper.from_string(out_pin),
                owner="estop",
            )
        )
        if not EstopHalMapper._owns_iocontrol_chain(out_pin, mcus_by_id):
            return
        fragment.nets.append("net estop-out <= iocontrol.0.user-enable-out")

    @staticmethod
    def _owns_iocontrol_chain(
        pin_string: str, mcus_by_id: dict[str, dict[str, Any]]
    ) -> bool:
        """False when the MCU this pin targets already claims
        `iocontrol.0`'s enable chain for its own link-health wiring."""
        mcu_id = PinStringMapper.from_string(pin_string).mcu_id
        mcu = mcus_by_id.get(mcu_id) or {}
        return CapabilityClass.for_connection(mcu.get("connection")) is not CapabilityClass.POSITION


__all__ = ["EstopHalMapper"]
