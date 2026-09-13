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

#: `pin_id` -> (the real `vfdmod` pin, direction). Verified against
#: `machine_config/example/PrintNC-WEBGUI/webgui_connections.hal`, a
#: real, working machine's own HAL wiring — not the unverified guess
#: this table used to be (`rpm-in` was `vfdmod.control.rpm-in`, which
#: doesn't exist on a real vfdmod build; the RPM command pin lives
#: under `vfdmod.spindle.*` alongside `rpm-out`, not `vfdmod.control.*`
#: with `run-forward`/`run-reverse`).
_PIN_MAP: dict[str, tuple[str, str]] = {
    "run-forward": ("vfdmod.control.run-forward", "out"),
    "run-reverse": ("vfdmod.control.run-reverse", "out"),
    "rpm-in": ("vfdmod.spindle.rpm-in", "out"),
    "rpm-out": ("vfdmod.spindle.rpm-out", "in"),
    "at-speed": ("vfdmod.spindle.at-speed", "in"),
    "fault": ("vfdmod.rs485.last-error", "in"),
    "is-connected": ("vfdmod.rs485.is-connected", "in"),
    "error-count": ("vfdmod.rs485.error-count", "in"),
}

#: Known-good ``vfdmod`` config — lifted verbatim from a real, working
#: PrintNC machine (``machine_config/example/PrintNC-WEBGUI/vfd.ini``),
#: same pattern as ``ini_template_generator._DISPLAY_DEFAULTS``. The
#: previous version of this file invented its own ``[common]`` /
#: ``[rpmIn]`` / ``[rpmOut]`` shape that does not match what ``vfdmod``
#: actually parses — real section names are ``[Common]`` / ``[RS485]``
#: / ``[Control]`` / ``[SpindleRpmIn]`` / ``[SpindleRpmOut]``, and the
#: fabricated shape had no ``MaxSpeedRPM``/``MinSpeedRPM`` at all,
#: which is exactly the "parameter is wrong or missing" failure at
#: LinuxCNC startup. The Modbus register map (``[Control]``,
#: ``[SpindleRpmIn]``/``[SpindleRpmOut]``, every ``[P00.xx]``-style
#: user parameter) is drive-specific and not ingested from the
#: profile yet (see the component doc) — copying the reference
#: machine's known-working register map is the only sane default
#: until a `model` field lands. Only the five values that a real
#: machine's own hardware actually varies — the two spindle RPM
#: limits and the three serial-link settings — are templated; every
#: other line is carried through unedited.
_VFD_INI_REFERENCE = """\
# **********************************************************
#
# Predefined (required) groups start here! These groups are:
#
# [Common]
# [RS485]
# [Control]
# [SpindleRpmIn]
# [SpindleRpmOut]
#
# **********************************************************

[Common]

# HAL component name. Default value is 'vfdmod'.
;ComponentName=vfdmod

# A maximum spindle speed shall be greater than zero.
MaxSpeedRPM={max_speed_rpm}

# A minimum spindle speed shall be greater than zero
# and lower than (or equal to) MaxSpeedRPM.
MinSpeedRPM={min_speed_rpm}

# A maximum allowed difference between command speed and output speed
# to set HAL 'at-speed' output to TRUE.
# 0.00 = 0%
# 1.00 = 100%
# Default value is 0.05 (5%).
;AtSpeedThreshold=0.05

[RS485]

# VFD slave address.
SlaveAddress={slave_address}

# Serial device system path.
SerialDevice={serial_device}

# Communication speed.
BaudRate={baud_rate}

# Data bits: always 8.
DataBits=8

# Parity: 'N' for none (default), 'E' for even, 'O' for odd.
Parity=N

# Stop bits: 1 (default) or 2.
StopBits=1

# Loop delay in milliseconds, default value is 200 ms.
# Range: 0 ... 10000.
;LoopDelay=200

# Delay in characters at front of every MODBUS request.
# MODBUS specification recommends at least 3.5 characters,
# so default value must be 4.
# Increase this value if communication errors happen.
# Range: 0 ... 100.
;ProtocolDelay=4

# A minimum count of successfull requests to set HAL 'is-connected' output
# to TRUE. Default value is 10. Range: 1 ... 100.
;IsConnectedDelay=10

# Comma separated critical errors that call reconnection event.
# For example: error code 5 occures when SerialDevice has been
# physically disconnected.
;ConnectionErrorList=5

# Delay in milliseconds between reconnection attempts, this parameter
# is active when ConnectionErrorList is not empty. Default value is 1000 ms.
# Range: 0 ... 10000.
;ConnectionDelay=1000

[Control]
# Function code:
# 0x06 - write single register (default).
# 0x10 - write multiple registers.
# 0x05 - write single coil.
# 0x0F - write multiple coils.
;FunctionCode=0x06

# **********************************************************
# Values below are active when FunctionCode is 0x06 or 0x10.
# **********************************************************

# An address of the control register.
Address=0x2000

# A value to run spindle forward.
RunForwardValue=0x0012

# A value to run spindle reverse.
RunReverseValue=0x0022

# A value to reset a fault state.
# If this parameter is commented then fault reset feature will be disabled.
;FaultResetValue=0x0080

# A value to stop spindle.
StopValue=0x0001

# **********************************************************
# Values below are active when FunctionCode is 0x05 or 0x0F.
# **********************************************************

# An address of the coil that turns spindle on.
;RunCoil=0x????

# An address of the coil that sets spindle direction.
;DirectionCoil=0x????

# An address of the coil that resets a fault state.
# If this parameter is commented then fault reset feature will be disabled.
;FaultResetCoil=0x????

[SpindleRpmIn]

# Function code:
# 0x06 - write single register (default).
# 0x10 - write multiple registers.
;FunctionCode=0x06

# An address of the command speed (or frequency) register.
Address=0x2001

# Multiplier and Divider are integer values to correct command speed value
# before it will be written to command speed register.
# Corrected command speed = (command speed) x Multiplier / Divider.
# Use both (Multiplier & Divider) to reach float coefficient.
Multiplier=1
Divider=6

[SpindleRpmOut]

# An address of the output speed (or frequency) register.
Address=0x200B

# Multiplier and Divider are integer values to correct output speed value
# after it has been read from output speed register.
# Corrected output speed = (output speed) x Multiplier / Divider.
# Use both (Multiplier & Divider) to reach float coefficient.
Multiplier=6
Divider=1

# **********************************************************
#
# User defined groups start here!
#
# Each user group can be named at user choice, spaces are
# allowed. For example:
# [User parameter 5]
# [123]
# [DC bus voltage]
# [output-current]
#
# Please note: group names are case insensitive, it means
# [My-Parameter] and [my-parameter] are the same.
#
# **********************************************************


[TargetFrequency]
FunctionCode=0x03
Address=0x200A
PinType=float
Multiplier=1
Divider=10
PinName=TargetFrequency

[TargetRpm]
FunctionCode=0x03
Address=0x200A
PinType=float
Multiplier=6
Divider=1
PinName=TargetRpm

[OutputCurrent]
FunctionCode=0x03
Address=0x200C
PinType=float
Multiplier=1
Divider=1
PinName=OutputCurent

[OutputVoltage]
FunctionCode=0x03
Address=0x200D
PinType=float
Multiplier=1
Divider=1
PinName=OutputVoltage

[MainLineVoltage]
FunctionCode=0x03
Address=0x200E
PinType=float
Multiplier=1
Divider=1
PinName=MainLineVoltage

[CurrentAccelerationTime]
FunctionCode=0x03
Address=0x2011
PinType=float
Multiplier=1
Divider=10
PinName=CurrentAccelerationTime

[CurrentDeAccelerationTime]
FunctionCode=0x03
Address=0x2012
PinType=float
Multiplier=1
Divider=10
PinName=CurrentDeAccelerationTime

[P00.00]
FunctionCode=0x03
Address=0x0000
PinType=float
Multiplier=1
Divider=10
PinName=P00.00

[P00.01]
FunctionCode=0x03
Address=0x0001
PinType=u32
Multiplier=1
Divider=1
PinName=P00.01

[P00.24]
functionCode=0x06
Address=0x0018
PinType=u32
Multiplier=1
Divider=1
PinName=P00.24

[P06.00]
FunctionCode=0x03
Address=0x0600
PinType=float
Multiplier=1
Divider=10
PinName=P06.00

[P06.01]
FunctionCode=0x03
Address=0x0601
PinType=float
Multiplier=1
Divider=10
PinName=P06.01

[P06.02]
FunctionCode=0x03
Address=0x0602
PinType=float
Multiplier=1
Divider=10
PinName=P06.02


[P11.00]
functionCode=0x06
Address=0x0B00
PinType=u32
Multiplier=1
Divider=1
PinName=P11.00

[P11.01]
functionCode=0x06
Address=0x0B01
PinType=u32
Multiplier=1
Divider=1
PinName=P11.01

[P11.02]
functionCode=0x06
Address=0x0B02
PinType=u32
Multiplier=1
Divider=1
PinName=P11.02

[P11.03]
functionCode=0x06
Address=0x0B03
PinType=u32
Multiplier=1
Divider=1
PinName=P11.03

[P11.04]
functionCode=0x06
Address=0x0B04
PinType=u32
Multiplier=1
Divider=1
PinName=P11.04
"""

#: Reference-file fallbacks for the five templated values, used only
#: when the profile/spindle didn't declare them — same numbers the
#: reference machine ships with.
_DEFAULT_MAX_SPEED_RPM = 24000
_DEFAULT_MIN_SPEED_RPM = 5000
_DEFAULT_SLAVE_ADDRESS = 1
_DEFAULT_SERIAL_DEVICE = "/dev/ttyUSB0"
_DEFAULT_BAUD_RATE = 19200


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

        The three serial settings come straight off the
        ``hardware.json`` MCU record (``interface``, ``baud_rate``,
        ``node_id`` — ingested from the `[mcu]` section); the spindle
        RPM range comes from the spindle tool routed to this MCU
        (``_spindle_min_rpm``/``_spindle_max_rpm``, stitched in by the
        assembler — see ``HalAssembler._route``, since a bare MCU
        record has no notion of "which spindle rides this bus").
        Anything undeclared falls back to the reference machine's own
        known-good values.
        """
        mcu_id = str(mcu.get("id", "mcu"))

        min_speed_rpm = mcu.get("_spindle_min_rpm")
        max_speed_rpm = mcu.get("_spindle_max_rpm")

        config_file = f"vfd_{mcu_id}.ini"
        ini = _VFD_INI_REFERENCE.format(
            max_speed_rpm=int(max_speed_rpm) if max_speed_rpm else _DEFAULT_MAX_SPEED_RPM,
            min_speed_rpm=int(min_speed_rpm) if min_speed_rpm else _DEFAULT_MIN_SPEED_RPM,
            slave_address=mcu.get("node_id") or _DEFAULT_SLAVE_ADDRESS,
            serial_device=mcu.get("interface") or _DEFAULT_SERIAL_DEVICE,
            baud_rate=mcu.get("baud_rate") or _DEFAULT_BAUD_RATE,
        )

        return HalFragment(
            loadusr=[f"loadusr -W vfdmod {config_file}"],
            files={config_file: ini},
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
