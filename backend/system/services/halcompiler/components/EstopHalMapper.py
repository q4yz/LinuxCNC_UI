"""The `[estop]` component's physical chain -> :class:`HalFragment`
(`.agent/component/estop.md`).

The UI half — `webgui.estop` -> `halui.estop.activate` — lives in
`webgui_connections.hal` via `EstopWebguiMapper`, not here:
`StateService.activate_estop()` (`backend/machine/services/
StateService.py`) now generates its own pulse (assert, hold briefly,
reset), so the HAL side is just a plain passthrough net, no different
in kind from a spindle's `TargetRpm` binding — it needs no `oneshot`
and no core `machine.hal` wiring at all.

This mapper covers only what's left: the **optional, per-pin physical
E-stop chain**. `fault_pin`/`out_pin` mirror the hand-wired chain in
the real reference machine, `machine_config/example/PrintNC-WEBGUI/
Machine.hal` (lines 41-57): an `estop_latch` gates LinuxCNC's own
enable state on a physical fault input, and a physical output pin
mirrors LinuxCNC's enable state back out (a lamp, a relay, a second
machine's E-stop loop). Each pin is independently optional, and
declaring neither (including a fully empty `[estop]` block) is valid
— this mapper then contributes nothing to `machine.hal` at all.

This chain is skipped on a class-B (Remora/EtherCAT) MCU: that
router's own `base_fragment()` already nets `iocontrol.0.
user-enable-out` / `user-request-enable` / `emc-enable-in` for its own
SPI/EtherCAT link-health chain (`RemoraRouterMapper.base_fragment`) —
wiring `estop_latch` on top of the *same* pins would double-drive
them, a genuine HAL load error, not a cosmetic one. The physical pin
itself is still routed (a `PinRequest` survives either way, so a
Remora `fault_pin` still becomes a real `config.txt` "Digital Pin"
module) — only the `iocontrol`/`estop_latch` linkage is skipped, and
only on the MCU that pin actually targets, never the whole machine.
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


class EstopHalMapper:
    """The `[estop]` component's optional physical E-stop chain."""

    @staticmethod
    def to_fragment(
        estop: dict[str, Any], mcus_by_id: dict[str, dict[str, Any]]
    ) -> HalFragment:
        fragment = HalFragment()

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
