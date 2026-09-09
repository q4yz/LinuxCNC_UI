"""One digital spindle -> :class:`HalFragment` (`.agent/component/digital_spindle.md` § 3).

Transport-independent: this mapper never mentions RS-485, Modbus or
EtherCAT. It emits the hardware-agnostic half of the spindle wiring
(scale stages, at-speed derivation, health exports) plus a
:class:`PinRequest` per declared pin; whichever MCU router owns the
pin's `<mcu_id>:` prefix supplies the other half. That split is what
lets one spindle template serve every transport (README § 2 — a
`vfd_rs485` MCU is capability class C, "carries a spindle, never a
joint").

Runs once per `tools[]` entry of `type == "spindle_digital"`,
independent of the machine's motion capability class — a spindle has
its own MCU and is never dispatched through
:class:`.StepperHalMapper`/:class:`.RemoraStepperHalMapper`.
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

#: `near` component tuning — spec's documented defaults (digital_spindle.md § 3).
_NEAR_SCALE = 1.02
#: Tolerance band fraction of `min_rpm` used when no `at_speed_pin` exists
#: and at-speed must be derived from `speed_fb_pin` instead.
_NEAR_DIFFERENCE_FRACTION = 0.05

#: (hardware.json field, health-signal suffix) — routed identically,
#: each independently optional (`.agent/component/digital_spindle.md` § 4).
_HEALTH_PINS: tuple[tuple[str, str], ...] = (
    ("fault_pin", "fault"),
    ("is_connected_pin", "is-connected"),
    ("error_count_pin", "error-count"),
)


class DigitalSpindleHalMapper:
    """Speed command, run/reverse, feedback/at-speed, health — one spindle."""

    @staticmethod
    def to_fragment(spindle: dict[str, Any]) -> HalFragment:
        fragment = HalFragment()
        spindle_id = str(spindle["id"])
        n = int(spindle.get("spindle_number") or 0)
        rpm_scale = spindle.get("rpm_scale")

        cmd_signal = DigitalSpindleHalMapper._speed_command(fragment, spindle_id, n, rpm_scale)
        DigitalSpindleHalMapper._request(fragment, spindle, "speed_pin", cmd_signal, PinRole.SPINDLE_OUT, spindle_id)

        DigitalSpindleHalMapper._run_reverse(fragment, spindle, spindle_id, n)
        DigitalSpindleHalMapper._feedback_and_at_speed(fragment, spindle, spindle_id, n)
        DigitalSpindleHalMapper._health(fragment, spindle, spindle_id)

        return fragment

    # -- speed command ---------------------------------------------------- #

    @staticmethod
    def _speed_command(fragment: HalFragment, spindle_id: str, n: int, rpm_scale: float | None) -> str:
        """Returns the signal the router should bind to `speed_pin`.

        Scaled (`rpm_scale not in (None, 1.0)`): a `scale` block sits
        between `spindle.N.speed-out` (RPM, the hardware-agnostic
        `spindle-speed-cmd` per README § 5) and the physical pin (drive
        units). Unscaled: no block to bridge, so the physical pin binds
        directly to `spindle-speed-cmd` itself — emitting a second net
        name for the same writer would be a HAL "already has writer"
        error.
        """
        scaled = rpm_scale is not None and rpm_scale != 1.0
        if not scaled:
            fragment.nets.append(f"net spindle-speed-cmd spindle.{n}.speed-out")
            return "spindle-speed-cmd"

        fragment.nets.append(f"net spindle-speed-cmd spindle.{n}.speed-out => scale-{spindle_id}-cmd.in")
        fragment.loadrt.append(f"loadrt scale names=scale-{spindle_id}-cmd")
        fragment.addf.append(Addf(f"scale-{spindle_id}-cmd", SERVO_THREAD, order=2))
        fragment.setp.append(f"setp scale-{spindle_id}-cmd.gain {rpm_scale}")
        cmd_signal = f"{spindle_id}-speed-out"
        fragment.nets.append(f"net {cmd_signal} scale-{spindle_id}-cmd.out")
        return cmd_signal

    # -- run / reverse ------------------------------------------------------ #

    @staticmethod
    def _run_reverse(fragment: HalFragment, spindle: dict[str, Any], spindle_id: str, n: int) -> None:
        fragment.nets.append(f"net spindle-forward spindle.{n}.forward")
        DigitalSpindleHalMapper._request(fragment, spindle, "run_pin", "spindle-forward", PinRole.SPINDLE_OUT, spindle_id)

        if spindle.get("reverse_pin"):
            fragment.nets.append(f"net spindle-reverse spindle.{n}.reverse")
            DigitalSpindleHalMapper._request(
                fragment, spindle, "reverse_pin", "spindle-reverse", PinRole.SPINDLE_OUT, spindle_id
            )

    # -- feedback + at-speed ------------------------------------------------ #

    @staticmethod
    def _feedback_and_at_speed(fragment: HalFragment, spindle: dict[str, Any], spindle_id: str, n: int) -> None:
        has_speed_fb = bool(spindle.get("speed_fb_pin"))
        has_at_speed = bool(spindle.get("at_speed_pin"))

        if has_speed_fb:
            rpm_scale = spindle.get("rpm_scale")
            gain = (1.0 / rpm_scale) if rpm_scale not in (None, 0) else 1.0
            fb_raw_signal = f"{spindle_id}-speed-fb-raw"
            fragment.loadrt.append(f"loadrt scale names=scale-{spindle_id}-fb")
            fragment.addf.append(Addf(f"scale-{spindle_id}-fb", SERVO_THREAD, order=0))
            fragment.setp.append(f"setp scale-{spindle_id}-fb.gain {gain}")
            fragment.nets.append(f"net {fb_raw_signal} => scale-{spindle_id}-fb.in")
            fragment.nets.append(f"net spindle-speed-fb scale-{spindle_id}-fb.out => spindle.{n}.speed-in")
            DigitalSpindleHalMapper._request(
                fragment, spindle, "speed_fb_pin", fb_raw_signal, PinRole.SPINDLE_IN, spindle_id
            )

        if has_at_speed:
            fragment.nets.append(f"net spindle-at-speed => spindle.{n}.at-speed")
            DigitalSpindleHalMapper._request(
                fragment, spindle, "at_speed_pin", "spindle-at-speed", PinRole.SPINDLE_IN, spindle_id
            )
        elif has_speed_fb:
            # No direct at-speed bit — derive one inside a tolerance
            # band around the commanded RPM (digital_spindle.md § 3).
            min_rpm = spindle.get("min_rpm") or 0
            near = f"near-{spindle_id}-at-speed"
            fragment.loadrt.append(f"loadrt near names={near}")
            fragment.addf.append(Addf(near, SERVO_THREAD, order=0))
            fragment.setp.extend(
                [
                    f"setp {near}.scale {_NEAR_SCALE}",
                    f"setp {near}.difference {min_rpm * _NEAR_DIFFERENCE_FRACTION}",
                ]
            )
            # Always the RPM-domain `spindle-speed-cmd`, never the
            # pin-routed command signal `_speed_command` returns — that
            # one is in drive units when scaled, and comparing drive
            # units against RPM feedback would compare the wrong thing.
            fragment.nets.extend(
                [
                    f"net spindle-speed-cmd => {near}.in1",
                    f"net spindle-speed-fb => {near}.in2",
                    f"net spindle-at-speed {near}.out => spindle.{n}.at-speed",
                ]
            )
        else:
            # Nothing drives at-speed — force it so G-code doesn't block
            # forever (W_NO_SPINDLE_FEEDBACK is the validator's warning
            # that this is happening).
            fragment.setp.append(f"setp spindle.{n}.at-speed true")

    # -- health -------------------------------------------------------------- #

    @staticmethod
    def _health(fragment: HalFragment, spindle: dict[str, Any], spindle_id: str) -> None:
        """One request per declared health pin — no net of its own here.

        Nothing in this component consumes fault/is-connected/error-count
        yet (the UI-bindings pass isn't built); the router's own `net`
        supplies the writer. Registering only the request, not a net,
        avoids emitting a target-less `net` statement.
        """
        for field, suffix in _HEALTH_PINS:
            if not spindle.get(field):
                continue
            signal = f"{spindle_id}-{suffix}"
            DigitalSpindleHalMapper._request(fragment, spindle, field, signal, PinRole.SPINDLE_IN, spindle_id)

    # -- shared -------------------------------------------------------------- #

    @staticmethod
    def _request(
        fragment: HalFragment,
        spindle: dict[str, Any],
        field: str,
        signal: str,
        role: PinRole,
        owner: str,
    ) -> None:
        raw = spindle.get(field)
        if not raw:
            return
        fragment.requests.append(
            PinRequest(signal=signal, role=role, pin=PinStringMapper.from_string(raw), owner=owner)
        )


__all__ = ["DigitalSpindleHalMapper"]
