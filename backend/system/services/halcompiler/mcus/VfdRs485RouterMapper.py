"""VFD-on-RS485 MCU: base emission + pin routing.

`.agent/component/mcu_vfd_rs485.md` § 3 (`loadusr -W vfdmod`, the
`vfd.ini` sidecar) and § 4 (the pin router — class C, one peripheral,
never motion). `pin_id` here is not a GPIO number but a **logical
drive function** (`run-forward`, `rpm-out`, ...) — the router looks it
up in a fixed table rather than allocating an index the way
:class:`.RemoraRouterMapper` does for its inputs.
"""

from __future__ import annotations

from typing import Any

from models.machineconfig.hal_fragment_models import SERVO_THREAD, Addf, HalFragment, PinRequest

#: `pin_id` -> (the real `vfdmod` pin, direction). `.agent/component/
#: mcu_vfd_rs485.md` § 4's table — third-party pin names, unverified
#: against a specific vfdmod build (see that file's closing note).
_PIN_MAP: dict[str, tuple[str, str]] = {
    "run-forward": ("vfdmod.control.run-forward", "out"),
    "run-reverse": ("vfdmod.control.run-reverse", "out"),
    "rpm-in": ("vfdmod.control.rpm-in", "out"),
    "rpm-out": ("vfdmod.spindle.rpm-out", "in"),
    "at-speed": ("vfdmod.spindle.at-speed", "in"),
    "fault": ("vfdmod.rs485.last-error", "in"),
    "is-connected": ("vfdmod.rs485.is-connected", "in"),
    "error-count": ("vfdmod.rs485.error-count", "in"),
}


class UnknownVfdPinError(ValueError):
    """A spindle pin names a `pin_id` this router doesn't recognise.

    The spec calls this ``E_PIN_UNAVAILABLE`` and treats it as a
    validator rule; this compiler doesn't implement that check yet
    (`.agent/HANDOFF.md`), so the router raises defensively instead of
    emitting a `net` against a `vfdmod` pin that doesn't exist — that
    fails at HAL load with a far less obvious message.
    """


class VfdRs485RouterMapper:
    """Routes :class:`PinRequest` entries whose ``pin.mcu_id`` is this MCU."""

    @staticmethod
    def base_fragment(mcu: dict[str, Any]) -> HalFragment:
        """§ 3 — the userspace component load plus its `vfd.ini` sidecar.

        Class C: no `addf` at all. `vfdmod` polls the bus at its own
        rate in userspace; nothing safety- or motion-critical may
        depend on it, which is exactly why a VFD link is class C.

        Serial settings come straight off the `hardware.json` MCU
        record (`interface`, `baud_rate`, `node_id`, `parity` —
        ingested from the `[mcu]` section and normalised by the
        parser); anything undeclared falls back to the documented
        vfdmod defaults.
        """
        mcu_id = str(mcu.get("id", "mcu"))
        port = str(mcu.get("interface") or "")

        config_file = f"vfd_{mcu_id}.ini"
        ini = "\n".join(
            [
                "[common]",
                f"address  = {mcu.get('node_id', 1)}",
                f"port     = {port}",
                f"baud     = {mcu.get('baud_rate', 9600)}",
                f"parity   = {mcu.get('parity', 'none')}",
                "databits = 8",
                "stopbits = 1",
                "",
                "[rpmIn]",
                "address    = ",
                "multiplier = 1",
                "divider    = 1",
                "",
                "[rpmOut]",
                "address    = ",
                "multiplier = 1",
                "divider    = 1",
            ]
        )

        return HalFragment(
            loadusr=[f"loadusr -W vfdmod {config_file}"],
            files={config_file: ini + "\n"},
        )

    @staticmethod
    def route(requests: list[PinRequest]) -> HalFragment:
        """§ 4 — one `net` per request, `not` stage inserted for an inverted pin."""
        fragment = HalFragment()
        for request in requests:
            target = _PIN_MAP.get(request.pin.pin_id)
            if target is None:
                raise UnknownVfdPinError(
                    f"{request.owner}: {request.pin.raw!r} names pin_id "
                    f"{request.pin.pin_id!r}, which vfdmod does not expose "
                    f"(expected one of {sorted(_PIN_MAP)})"
                )
            hal_pin, direction = target
            if request.pin.invert:
                VfdRs485RouterMapper._route_inverted(fragment, request, hal_pin, direction)
            elif direction == "out":
                fragment.nets.append(f"net {request.signal} => {hal_pin}")
            else:
                fragment.nets.append(f"net {request.signal} <= {hal_pin}")
        return fragment

    @staticmethod
    def _route_inverted(fragment: HalFragment, request: PinRequest, hal_pin: str, direction: str) -> None:
        """`vfdmod` has no invert parameter — an explicit `not` stage instead.

        Named after the request, not the pin, so two different spindle
        pins routed through the same MCU never collide on one `not`
        instance.
        """
        not_name = f"not-{request.owner}-{request.role.value}"
        raw_signal = f"{request.signal}-raw"
        order = 2 if direction == "out" else 0
        fragment.loadrt.append(f"loadrt not names={not_name}")
        fragment.addf.append(Addf(not_name, SERVO_THREAD, order=order))
        if direction == "out":
            fragment.nets.append(f"net {request.signal} => {not_name}.in")
            fragment.nets.append(f"net {raw_signal} {not_name}.out => {hal_pin}")
        else:
            fragment.nets.append(f"net {raw_signal} {hal_pin} => {not_name}.in")
            fragment.nets.append(f"net {request.signal} {not_name}.out")


__all__ = ["UnknownVfdPinError", "VfdRs485RouterMapper"]
