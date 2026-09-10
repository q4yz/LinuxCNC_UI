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


class _SpindleContext:
    """Encapsulates state for a single spindle mapping pass to eliminate parameter bloat."""

    def __init__(self, spindle: dict[str, Any]) -> None:
        self.spindle = spindle
        self.fragment = HalFragment()
        self.spindle_id = str(spindle["id"])
        self.n = int(spindle.get("spindle_number") or 0)

    def request(self, field: str, signal: str, role: PinRole) -> None:
        """Helper to conditionally append a PinRequest if the field exists."""
        raw = self.spindle.get(field)
        if raw:
            self.fragment.requests.append(
                PinRequest(
                    signal=signal,
                    role=role,
                    pin=PinStringMapper.from_string(raw),
                    owner=self.spindle_id
                )
            )

    def build_speed_command(self) -> None:
        """Generates speed scaling logic and routes the speed command pin."""
        rpm_scale = self.spindle.get("rpm_scale")
        scaled = rpm_scale is not None and rpm_scale != 1.0

        if not scaled:
            self.fragment.nets.append(f"net spindle-speed-cmd spindle.{self.n}.speed-out")
            self.request("speed_pin", "spindle-speed-cmd", PinRole.SPINDLE_OUT)
            return

        self.fragment.nets.append(f"net spindle-speed-cmd spindle.{self.n}.speed-out => scale-{self.spindle_id}-cmd.in")
        self.fragment.loadrt.append(f"loadrt scale names=scale-{self.spindle_id}-cmd")
        self.fragment.addf.append(Addf(f"scale-{self.spindle_id}-cmd", SERVO_THREAD, order=2))
        self.fragment.setp.append(f"setp scale-{self.spindle_id}-cmd.gain {rpm_scale}")

        cmd_signal = f"{self.spindle_id}-speed-out"
        self.fragment.nets.append(f"net {cmd_signal} scale-{self.spindle_id}-cmd.out")
        self.request("speed_pin", cmd_signal, PinRole.SPINDLE_OUT)

    def build_run_reverse(self) -> None:
        self.fragment.nets.append(f"net spindle-forward spindle.{self.n}.forward")
        self.request("run_pin", "spindle-forward", PinRole.SPINDLE_OUT)

        if self.spindle.get("reverse_pin"):
            self.fragment.nets.append(f"net spindle-reverse spindle.{self.n}.reverse")
            self.request("reverse_pin", "spindle-reverse", PinRole.SPINDLE_OUT)

    def build_feedback_and_at_speed(self) -> None:
        has_speed_fb = bool(self.spindle.get("speed_fb_pin"))
        has_at_speed = bool(self.spindle.get("at_speed_pin"))

        if has_speed_fb:
            rpm_scale = self.spindle.get("rpm_scale")
            gain = (1.0 / rpm_scale) if rpm_scale not in (None, 0) else 1.0
            fb_raw_signal = f"{self.spindle_id}-speed-fb-raw"

            self.fragment.loadrt.append(f"loadrt scale names=scale-{self.spindle_id}-fb")
            self.fragment.addf.append(Addf(f"scale-{self.spindle_id}-fb", SERVO_THREAD, order=0))
            self.fragment.setp.append(f"setp scale-{self.spindle_id}-fb.gain {gain}")
            self.fragment.nets.append(f"net {fb_raw_signal} => scale-{self.spindle_id}-fb.in")
            self.fragment.nets.append(f"net spindle-speed-fb scale-{self.spindle_id}-fb.out => spindle.{self.n}.speed-in")

            self.request("speed_fb_pin", fb_raw_signal, PinRole.SPINDLE_IN)

        if has_at_speed:
            self.fragment.nets.append(f"net spindle-at-speed => spindle.{self.n}.at-speed")
            self.request("at_speed_pin", "spindle-at-speed", PinRole.SPINDLE_IN)
        elif has_speed_fb:
            min_rpm = self.spindle.get("min_rpm") or 0
            near = f"near-{self.spindle_id}-at-speed"

            self.fragment.loadrt.append(f"loadrt near names={near}")
            self.fragment.addf.append(Addf(near, SERVO_THREAD, order=0))
            self.fragment.setp.extend([
                f"setp {near}.scale {_NEAR_SCALE}",
                f"setp {near}.difference {min_rpm * _NEAR_DIFFERENCE_FRACTION}",
            ])
            self.fragment.nets.extend([
                f"net spindle-speed-cmd => {near}.in1",
                f"net spindle-speed-fb => {near}.in2",
                f"net spindle-at-speed {near}.out => spindle.{self.n}.at-speed",
            ])
        else:
            self.fragment.setp.append(f"setp spindle.{self.n}.at-speed true")

    def build_health(self) -> None:
        for field, suffix in _HEALTH_PINS:
            if self.spindle.get(field):
                self.request(field, f"{self.spindle_id}-{suffix}", PinRole.SPINDLE_IN)


class DigitalSpindleHalMapper:
    """Speed command, run/reverse, feedback/at-speed, health — one spindle."""

    @staticmethod
    def to_fragment(spindle: dict[str, Any]) -> HalFragment:
        ctx = _SpindleContext(spindle)

        ctx.build_speed_command()
        ctx.build_run_reverse()
        ctx.build_feedback_and_at_speed()
        ctx.build_health()

        return ctx.fragment


__all__ = ["DigitalSpindleHalMapper"]