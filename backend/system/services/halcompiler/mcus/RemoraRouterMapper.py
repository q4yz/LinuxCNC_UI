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
from models.machineconfig.HalFragmentModels import (
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
#: Digital inputs / outputs per board — the SPI frame's 16-bit words
#: (`remora.input.NN` / `remora.output.NN`), shared with its CAN nodes.
_DIGITAL_BITS = 16

_THERMISTOR_CURVES: dict[str, tuple[int, int, int]] = {
    "generic 3950": (3950, 100000, 25),
}


class RemoraRouterMapper:
    """Routes :class:`PinRequest` entries whose ``pin.mcu_id`` is this MCU."""

    @staticmethod
    def base_fragment(mcu: dict[str, Any]) -> HalFragment:
        """§ 3 — component load, E-stop/SPI chain, thread attachment,
        plus the board's own `"Reset Pin"` firmware module when
        `board_reset_pin` is declared. MCU-intrinsic, same as the SPI-enable
        chain above it — not something any routed request triggers."""
        params = mcu.get("parameters") or {}
        chip = str(params.get("chip", "stm32")).strip().lower()

        if chip == _LPC_CHIP:
            loadrt = ["loadrt remora_lpc"]
        else:
            loadrt = ["loadrt remora-spi " + " ".join(RemoraRouterMapper._driver_params(mcu))]

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

        # Fault sources gating LinuxCNC's enable on top of the SPI link:
        # `[estop] fault_pin` read through this board (e.g. a relay
        # contact on the motor supply) and the CAN "Status Bit" (0 while
        # a mandatory node is missing — its `.not` twin is the fault).
        faults: list[str] = []
        if mcu.get("_estop_fault"):
            faults.append("estop-fault")
        can_status_bit = mcu.get("_can_status_bit")
        if can_status_bit is not None:
            faults.append("can-fault")
        if faults:
            # LinuxCNC may only run while the SPI link is up AND no fault
            # is present. `estop_latch` ANDs both (`ok-in` / `fault-in`)
            # and latches a dropout until the operator resets
            # (`user-request-enable`, the same edge that re-syncs the SPI
            # link). remora.read (order 0) sets SPI-status before the
            # latch (order 1) sees the reset; two faults are ORed first
            # (or2 also order 1, emitted before the latch: a stable sort).
            fragment.loadrt.append("loadrt estop_latch")
            if len(faults) > 1:
                fragment.loadrt.append("loadrt or2 names=estop-fault-or")
                fragment.addf.append(Addf("estop-fault-or", SERVO_THREAD, order=1))
            fragment.addf.append(Addf("estop-latch.0", SERVO_THREAD, order=1))
            fragment.nets = [
                "net user-enable-out <= iocontrol.0.user-enable-out => remora.SPI-enable",
                "net user-request-enable <= iocontrol.0.user-request-enable => remora.SPI-reset estop-latch.0.reset",
                "net remora-status <= remora.SPI-status => estop-latch.0.ok-in",
            ]
            if can_status_bit is not None:
                fragment.nets.append(f"net can-fault <= remora.input.{int(can_status_bit):02d}.not")
            if len(faults) > 1:
                fragment.nets += [
                    "net estop-fault => estop-fault-or.in0",
                    "net can-fault => estop-fault-or.in1",
                    "net estop-fault-any <= estop-fault-or.out => estop-latch.0.fault-in",
                ]
            else:
                fragment.nets.append(f"net {faults[0]} => estop-latch.0.fault-in")
            fragment.nets.append("net estop-ext <= estop-latch.0.ok-out => iocontrol.0.emc-enable-in")

        board_reset_pin = mcu.get("board_reset_pin")
        if board_reset_pin:
            parsed = PinStringMapper.from_string(board_reset_pin)
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
    def _driver_params(mcu: dict[str, Any]) -> list[str]:
        """``loadrt remora-spi`` parameters for the declared host side.

        The SPI clock is ``SPI_freq`` (Hz — the generic spidev driver on
        the BTT CB1, the Pi 5 driver) or ``SPI_clk_div`` (the bcm2835
        divider on a Pi 3/4; the parser keeps them exclusive), with
        ``SPI_clk_div=64`` when neither is declared. ``reset_pin`` is a
        host GPIO here, not the board-side ``board_reset_pin``.
        """
        params = mcu.get("parameters") or {}
        driver: list[str] = []
        if mcu.get("pru_base_freq"):
            driver.append(f"PRU_base_freq={mcu['pru_base_freq']}")
        if mcu.get("spi_freq"):
            driver.append(f"SPI_freq={mcu['spi_freq']}")
        else:
            driver.append(f"SPI_clk_div={mcu.get('spi_clk_div') or params.get('spi_clk_div', 64)}")
        for key, param in (
            ("interface", "spi_dev"),
            ("spi_cs_pin", "spi_cs_pin"),
            ("spi_cs_chip", "spi_cs_chip"),
            ("reset_pin", "reset_pin"),
            ("reset_chip", "reset_chip"),
        ):
            if mcu.get(key):
                driver.append(f"{param}={mcu[key]}")
        return driver

    @staticmethod
    def config_sync_line(mcu: dict[str, Any], config_file: str) -> str | None:
        """``loadusr -w remora-upload --sync ... config_<mcu>.txt``.

        Runs before ``loadrt remora-spi`` (the driver then owns the SPI
        link): the board compares the CRC-32 of the ``config.txt`` it
        booted with and only rewrites its SD card when it differs; with
        ``-w`` a failed sync stops LinuxCNC instead of running a board
        with a stale pin configuration. Same device, chip select and
        clock as the driver line. ``None`` for an LPC board (no SD
        upload) or ``sync_config: false`` (firmware without it).
        """
        params = mcu.get("parameters") or {}
        if str(params.get("chip", "stm32")).strip().lower() == _LPC_CHIP or mcu.get("sync_config") is False:
            return None
        return " ".join(["loadusr", "-w", "remora-upload", "--sync", *RemoraRouterMapper.link_args(mcu), config_file])

    @staticmethod
    def link_args(mcu: dict[str, Any]) -> list[str]:
        """``remora-upload`` options for the link the driver line uses —
        spidev, GPIO chip select and SPI clock. Shared by the HAL sync
        line and the manual upload (``RemoraBoardUploader``)."""
        args: list[str] = []
        if mcu.get("interface"):
            args += ["-d", str(mcu["interface"])]
        if mcu.get("spi_cs_pin"):
            args += ["--spi-cs-pin", str(mcu["spi_cs_pin"])]
        if mcu.get("spi_cs_chip"):
            args += ["--spi-cs-chip", str(mcu["spi_cs_chip"])]
        if mcu.get("spi_freq"):
            args += ["-s", str(mcu["spi_freq"])]
        return args

    @staticmethod
    def route(requests: list[PinRequest], reserved_input: int | None = None) -> HalFragment:
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

        ``DIGITAL_OUT`` has its own bit-space: `remora.output.NN` and a
        "Digital Pin" with ``Mode: Output`` — the shape of the Remora-m8p
        fork's verified sample (`Firmware/ConfigSamples/BTT_EBB42`). Its
        ``Safe State`` — the *physical* level while LinuxCNC is
        disconnected (the firmware does not apply ``Invert`` to it) — is
        always Low, inverted pin or not: the machine must be safe at Low. Inversion is the module's ``Invert`` key here — outputs have
        no HAL-side `.not` twin.
        """
        fragment = HalFragment()
        # The CAN "Status Bit" (``reserved_input``) is a hub input bit
        # too — the firmware owns it, so no Digital Pin may take it.
        inputs = (bit for bit in range(_DIGITAL_BITS) if bit != reserved_input)
        digital_out_index = 0
        sp_index = 0
        pv_index = 0
        for request in requests:
            if request.role in (PinRole.ENDSTOP, PinRole.DIGITAL_IN):
                bit = next(inputs, None)
                if bit is None:
                    raise ValueError(
                        f"{request.owner}: more than {_DIGITAL_BITS - (reserved_input is not None)} digital "
                        "inputs on one Remora board (its nodes included)"
                    )
                nn = f"{bit:02d}"
                # Writer only — the component mapper already emitted the
                # reader side (`net <signal> => joint.N....`) as a separate
                # `net` line; HAL lets the same net name accumulate pins
                # across statements, matching the reference file's split.
                # `^` (pullup) is a real modifier the firmware's
                # config.txt parser accepts on a "Digital Pin"'s
                # ``Pin`` string. A leading ``!`` for inversion is
                # not — confirmed against real Remora hardware, where
                # writing it breaks the pin (the parser doesn't
                # recognise it as a modifier the way it does `^`).
                # Inversion happens HAL-side instead: the Remora driver
                # exports an inverted twin `remora.input.NN.not` next
                # to every `remora.input.NN` (same idea as parport's
                # `-in-not`), so `!PG6` reads the `.not` pin.
                suffix = ".not" if request.pin.invert else ""
                fragment.nets.append(f"net {request.signal} remora.input.{nn}{suffix}")
                pullup = "^" if request.pin.pullup else ""
                firmware_pin = RemoraFirmwarePinMapper.to_firmware_pin(request.pin.pin_id)
                pin = f"{pullup}{firmware_pin}"
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
                            "Data Bit": bit,
                        },
                    )
                )
            elif request.role is PinRole.DIGITAL_OUT:
                if digital_out_index >= _DIGITAL_BITS:
                    raise ValueError(
                        f"{request.owner}: more than {_DIGITAL_BITS} digital outputs on one Remora board "
                        "(its nodes included)"
                    )
                nn = f"{digital_out_index:02d}"
                fragment.nets.append(f"net {request.signal} => remora.output.{nn}")
                module: dict[str, object] = {
                    "Name": f"digital_out_{request.owner}",
                    "Thread": "Servo",
                    "Type": "Digital Pin",
                    "Comment": request.owner,
                    "Pin": RemoraFirmwarePinMapper.to_firmware_pin(request.pin.pin_id),
                    "Mode": "Output",
                    "Data Bit": digital_out_index,
                    "Safe State": "Low",
                }
                if request.pin.invert:
                    module["Invert"] = "True"
                fragment.firmware_modules.append(
                    FirmwareModuleRequest(mcu_id=request.pin.mcu_id, module=module)
                )
                digital_out_index += 1
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
