"""Parallel-port MCU: base emission + pin routing.

`.agent/component/mcu_parallelport.md` § 3 (base `loadrt`/`addf`) and
§ 4 (the pin router — class A, step/dir realtime). Single-port only:
``port_index`` is always ``0``, matching the spec's
``computed.port_index = 0``.
"""

from __future__ import annotations

from typing import Any

from models.machineconfig.hal_fragment_models import (
    BASE_THREAD,
    Addf,
    HalFragment,
    PinRequest,
    PinRole,
)

_PORT_INDEX = 0

#: Roles routed as a parport OUTPUT pin (the component already wrote
#: the signal; the router adds the consumer). ENDSTOP is the one INPUT
#: role — the router adds the signal's writer instead.
_OUTPUT_ROLES = {PinRole.STEP, PinRole.DIR, PinRole.ENABLE}


class ParportRouterMapper:
    """Routes :class:`PinRequest` entries whose ``pin.mcu_id`` is this MCU."""

    @staticmethod
    def base_fragment(mcu: dict[str, Any]) -> HalFragment:
        """§ 3 — the driver load, independent of what ends up wired to it.

        ``interface`` is the real ingested field (the port address —
        ``"0"`` or a hex string like ``"0x378"``, `mcu_parallelport.md`
        § 1); ``direction``/``reset_time`` have no `[mcu]` schema keys
        yet (same file's "timing keys are not ingested yet" note), so
        they stay the documented defaults until that lands.
        """
        address = mcu.get("interface") or "0"
        direction = "out"
        reset_time = 2500

        return HalFragment(
            loadrt=[f'loadrt hal_parport cfg="{address} {direction}"'],
            setp=[f"setp parport.{_PORT_INDEX}.reset-time {reset_time}"],
            addf=[
                Addf(f"parport.{_PORT_INDEX}.read", BASE_THREAD, order=0),
                Addf(f"parport.{_PORT_INDEX}.write", BASE_THREAD, order=2),
                Addf(f"parport.{_PORT_INDEX}.reset", BASE_THREAD, order=3),
            ],
        )

    @staticmethod
    def route(requests: list[PinRequest]) -> HalFragment:
        """§ 4 — one `net` (+ `setp`) pair per request."""
        fragment = HalFragment()
        for request in requests:
            pin_id = ParportRouterMapper._normalize_pin_id(request.pin.pin_id)
            invert = "1" if request.pin.invert else "0"

            if request.role in _OUTPUT_ROLES:
                fragment.nets.append(
                    f"net {request.signal} => parport.{_PORT_INDEX}.pin-{pin_id}-out"
                )
                if request.role is PinRole.STEP:
                    fragment.setp.append(
                        f"setp parport.{_PORT_INDEX}.pin-{pin_id}-out-reset 1"
                    )
                fragment.setp.append(
                    f"setp parport.{_PORT_INDEX}.pin-{pin_id}-out-invert {invert}"
                )
            elif request.role is PinRole.ENDSTOP:
                suffix = "in-not" if request.pin.invert else "in"
                fragment.nets.append(
                    f"net {request.signal} <= parport.{_PORT_INDEX}.pin-{pin_id}-{suffix}"
                )

        return fragment

    @staticmethod
    def _normalize_pin_id(pin_id: str) -> str:
        """`"2"` -> `"02"` — parport pins are two digits (`pin-NN-*`).

        Left untouched if not purely numeric; a malformed pin id is a
        validator concern (`E_MALFORMED_PIN`), not this router's.
        """
        return pin_id.zfill(2) if pin_id.isdigit() else pin_id


__all__ = ["ParportRouterMapper"]
