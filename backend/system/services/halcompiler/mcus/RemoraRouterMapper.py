"""Remora SPI MCU: base emission + pin routing.

`.agent/component/mcu_spi_remora.md` § 3 (base `loadrt`/E-stop chain/
`addf`) and § 4 (the pin router — endstops, plus `remora.SP.N`/
`remora.PV.N` for heater/fan/spindle analog channels).

The SPI link doubles as the watchdog (§ 3): `SPI-enable`/`SPI-reset`/
`SPI-status` are wired unconditionally in ``base_fragment``, the same
way :class:`ParportRouterMapper` always wires its own reset-time setup
— MCU-intrinsic, not something any request triggers.
"""

from __future__ import annotations

from typing import Any

from mappers.machineconfig import RemoraFirmwarePinMapper
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
        """§ 4 — digital inputs (endstops) + analog SP/PV channels.

        Each role gets its **own** index counter. Sharing one
        `enumerate()` index across roles would leave gaps the moment a
        machine mixes endstops with heaters (ender3 does exactly
        this) — request 3 being an ``ANALOG_OUT`` must not burn
        `remora.input.03` that request 4's endstop then never gets.
        """
        fragment = HalFragment()
        endstop_index = 0
        sp_index = 0
        pv_index = 0
        for request in requests:
            if request.role is PinRole.ENDSTOP:
                nn = f"{endstop_index:02d}"
                endstop_index += 1
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
                firmware_pin = RemoraFirmwarePinMapper.to_firmware_pin(request.pin.pin_id)
                pin = f"{invert}{pullup}{firmware_pin}"
                fragment.firmware_modules.append(
                    FirmwareModuleRequest(
                        mcu_id=request.pin.mcu_id,
                        module={
                            "Name": f"endstop_{request.owner}",
                            "Thread": "Servo",
                            # "Digital Pin" (with the space) — the real
                            # reference config.txt's literal key; not a
                            # guess (machine_config/example/ender3/config.txt).
                            "Type": "Digital Pin",
                            "Comment": request.owner,
                            "Pin": pin,
                            "Mode": "Input",
                            "Data Bit": endstop_index - 1,
                        },
                    )
                )
            elif request.role is PinRole.ANALOG_OUT:
                fragment.nets.append(f"net {request.signal} => remora.SP.{sp_index}")
                firmware_pin = RemoraFirmwarePinMapper.to_firmware_pin(request.pin.pin_id)
                fragment.firmware_modules.append(
                    FirmwareModuleRequest(
                        mcu_id=request.pin.mcu_id,
                        module={
                            "Name": f"pwm_{request.owner}",
                            "Thread": "Servo",
                            "Type": "PWM",
                            "Comment": request.owner,
                            "SP[i]": sp_index,
                            "PWM Pin": firmware_pin,
                        },
                    )
                )
                sp_index += 1
            elif request.role is PinRole.ANALOG_IN:
                fragment.nets.append(f"net {request.signal} <= remora.PV.{pv_index}")
                # No "Temperature" module here — the real reference
                # module (config.txt's temp_bed/temp_extruder entries)
                # needs a thermistor curve (Sensor + beta/r0/t0) that
                # temperature_sensors[] doesn't carry yet. Fabricating
                # placeholder curve values would silently misreport
                # real temperatures, which is worse than the honest
                # gap — see .agent/HANDOFF.md.
                pv_index += 1
        return fragment


__all__ = ["RemoraRouterMapper"]
