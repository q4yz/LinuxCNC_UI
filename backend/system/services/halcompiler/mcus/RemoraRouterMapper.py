"""Remora SPI MCU: base emission + pin routing.

`.agent/component/mcu_spi_remora.md` § 3 (base `loadrt`/E-stop chain/
`addf`) and § 4 (the pin router — class B, digital input only; Phase 2
carries no heater/fan/spindle components yet, so `remora.SP.N`/
`remora.PV.N` routing has nothing to call it).

The SPI link doubles as the watchdog (§ 3): `SPI-enable`/`SPI-reset`/
`SPI-status` are wired unconditionally in ``base_fragment``, the same
way :class:`ParportRouterMapper` always wires its own reset-time setup
— MCU-intrinsic, not something any request triggers.
"""

from __future__ import annotations

from typing import Any

from models.machineconfig.hal_fragment_models import (
    SERVO_THREAD,
    Addf,
    FirmwareModuleRequest,
    HalFragment,
    PinRequest,
    PinRole,
)

#: `chip: "lpc17xx"` loads the LPC-target component instead of the
#: default STM32 SPI one — `mcu_spi_remora.md` § 2's `computed.component`.
_LPC_CHIP = "lpc17xx"


class RemoraRouterMapper:
    """Routes :class:`PinRequest` entries whose ``pin.mcu_id`` is this MCU."""

    @staticmethod
    def base_fragment(mcu: dict[str, Any]) -> HalFragment:
        """§ 3 — component load, E-stop/SPI chain, thread attachment."""
        params = mcu.get("parameters") or {}
        chip = str(params.get("chip", "stm32")).strip().lower()

        if chip == _LPC_CHIP:
            loadrt = ["loadrt remora_lpc"]
        else:
            spi_clk_div = params.get("spi_clk_div", 64)
            loadrt = [f"loadrt remora-spi SPI_clk_div={spi_clk_div}"]

        return HalFragment(
            loadrt=loadrt,
            nets=[
                "net user-enable-out <= iocontrol.0.user-enable-out => remora.SPI-enable",
                "net user-request-enable <= iocontrol.0.user-request-enable => remora.SPI-reset",
                "net remora-status <= remora.SPI-status => iocontrol.0.emc-enable-in",
            ],
            addf=[
                Addf("remora.read", SERVO_THREAD, order=0),
                Addf("remora.update-freq", SERVO_THREAD, order=2),
                Addf("remora.write", SERVO_THREAD, order=2),
            ],
        )

    @staticmethod
    def route(requests: list[PinRequest]) -> HalFragment:
        """§ 4 — digital inputs only; each gets a zero-padded `remora.input.NN`."""
        fragment = HalFragment()
        for index, request in enumerate(requests):
            if request.role is not PinRole.ENDSTOP:
                continue
            nn = f"{index:02d}"
            # Writer only — the component mapper already emitted the
            # reader side (`net <signal> => joint.N....`) as a separate
            # `net` line; HAL lets the same net name accumulate pins
            # across statements, matching the reference file's split.
            fragment.nets.append(f"net {request.signal} remora.input.{nn}")
            # Inversion is firmware-side here (spec § 4), not a HAL
            # `-not` twin as parport has — both modifiers fold into the
            # pin string `config.txt` carries.
            invert = "!" if request.pin.invert else ""
            pullup = "^" if request.pin.pullup else ""
            pin = f"{invert}{pullup}{request.pin.pin_id}"
            fragment.firmware_modules.append(
                FirmwareModuleRequest(
                    mcu_id=request.pin.mcu_id,
                    module={
                        "Thread": "Servo",
                        "Type": "DigitalPin",
                        "Comment": request.owner,
                        "Pin": pin,
                        "Mode": "Input",
                        "Data Bit": index,
                    },
                )
            )
        return fragment


__all__ = ["RemoraRouterMapper"]
