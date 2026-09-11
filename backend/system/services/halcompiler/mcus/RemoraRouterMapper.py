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

from mappers.machineconfig import PinStringMapper, RemoraFirmwarePinMapper
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

#: ``temperature_sensors[].type`` -> ``(beta, r0 ohms, t0 degC)``.
#: "Generic 3950" is the standard NTC 100K B3950 curve Klipper/Marlin
#: ship as their own default — verified against the real, working
#: `machine_config/example/ender3/config.txt`'s `temp_extruder`/
#: `temp_bed` modules, not derived from generic thermistor tables.
#: Lookup is case-insensitive (`.cfg` authors capitalise inconsistently).
#: A `type` not listed here is an honest gap: no module is emitted
#: rather than guessing a curve that would silently misreport real
#: temperatures.
_THERMISTOR_CURVES: dict[str, tuple[int, int, int]] = {
    "generic 3950": (3950, 100000, 25),
}


class RemoraRouterMapper:
    """Routes :class:`PinRequest` entries whose ``pin.mcu_id`` is this MCU."""

    @staticmethod
    def base_fragment(mcu: dict[str, Any]) -> HalFragment:
        """§ 3 — component load, E-stop/SPI chain, thread attachment,
        plus the board's own `"Reset Pin"` firmware module when
        `reset_pin` is declared. MCU-intrinsic, same as the SPI-enable
        chain above it — not something any routed request triggers."""
        params = mcu.get("parameters") or {}
        chip = str(params.get("chip", "stm32")).strip().lower()

        if chip == _LPC_CHIP:
            loadrt = ["loadrt remora_lpc"]
        else:
            spi_clk_div = params.get("spi_clk_div", 64)
            loadrt = [f"loadrt remora-spi SPI_clk_div={spi_clk_div}"]

        fragment = HalFragment(
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

        reset_pin = mcu.get("reset_pin")
        if reset_pin:
            parsed = PinStringMapper.from_string(reset_pin)
            fragment.firmware_modules.append(
                FirmwareModuleRequest(
                    mcu_id=str(mcu.get("id", "mcu")),
                    module={
                        "Name": "reset_pin",
                        "Thread": "Servo",
                        "Type": "Reset Pin",
                        "Comment": "Reset pin",
                        "Pin": RemoraFirmwarePinMapper.to_firmware_pin(parsed.pin_id),
                    },
                )
            )

        return fragment

    @staticmethod
    def route(requests: list[PinRequest]) -> HalFragment:
        """§ 4 — digital inputs (endstops, E-stop `fault_pin`, ...) +
        analog SP/PV channels.

        Each role *group* gets its **own** index counter. Sharing one
        `enumerate()` index across roles would leave gaps the moment a
        machine mixes endstops with heaters (ender3 does exactly
        this) — request 3 being an ``ANALOG_OUT`` must not burn
        `remora.input.03` that request 4's endstop then never gets.
        ``ENDSTOP`` and ``DIGITAL_IN`` share one counter/bit-space on
        purpose: both land on the same `remora.input.NN` array and the
        same firmware "Digital Pin"/``Mode: Input`` module shape — the
        *only* difference is the firmware module's ``Name`` (kept
        distinct so `config.txt` never calls an E-stop input pin
        "endstop_..."), not the routing itself.

        No ``DIGITAL_OUT`` case exists here — unlike ``ANALOG_OUT``
        (a verified "PWM" module), there is no real reference
        `config.txt` with a digital *output* module to ground one
        against (every real example only shows ``Mode: Input``). A
        `DIGITAL_OUT` request routed through this MCU is an honest
        gap, same class as `ANALOG_IN`'s missing thermistor module
        below — see `.agent/component/estop.md`.
        """
        fragment = HalFragment()
        digital_in_index = 0
        sp_index = 0
        pv_index = 0
        for request in requests:
            if request.role in (PinRole.ENDSTOP, PinRole.DIGITAL_IN):
                nn = f"{digital_in_index:02d}"
                digital_in_index += 1
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
                name_prefix = "endstop" if request.role is PinRole.ENDSTOP else "digital_in"
                fragment.firmware_modules.append(
                    FirmwareModuleRequest(
                        mcu_id=request.pin.mcu_id,
                        module={
                            "Name": f"{name_prefix}_{request.owner}",
                            "Thread": "Servo",
                            # "Digital Pin" (with the space) — the real
                            # reference config.txt's literal key; not a
                            # guess (machine_config/example/ender3/config.txt).
                            "Type": "Digital Pin",
                            "Comment": request.owner,
                            "Pin": pin,
                            "Mode": "Input",
                            "Data Bit": digital_in_index - 1,
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
                curve = _THERMISTOR_CURVES.get(
                    str(request.sensor_type or "").strip().lower()
                )
                if curve is not None:
                    beta, r0, t0 = curve
                    firmware_pin = RemoraFirmwarePinMapper.to_firmware_pin(request.pin.pin_id)
                    fragment.firmware_modules.append(
                        FirmwareModuleRequest(
                            mcu_id=request.pin.mcu_id,
                            module={
                                "Name": f"temp_{request.owner}",
                                "Thread": "Servo",
                                "Type": "Temperature",
                                "Comment": request.owner,
                                "PV[i]": pv_index,
                                "Sensor": "Thermistor",
                                "Thermistor": {
                                    "Pin": firmware_pin,
                                    "beta": beta,
                                    "r0": r0,
                                    "t0": t0,
                                },
                            },
                        )
                    )
                # An unrecognised (or absent) sensor type stays an
                # honest gap — no module, since a fabricated curve
                # would silently misreport real temperatures. The HAL
                # `net` line above is still emitted either way.
                pv_index += 1
        return fragment


__all__ = ["RemoraRouterMapper"]
