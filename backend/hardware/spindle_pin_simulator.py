"""Mock-mode simulator for spindle HAL pins.

The :mod:`hardware.hal_subscription_manager` returns ``False`` for
every HAL pin in mock mode. Spindle pins are not boolean — ``at_speed``
is bool, ``rpm_out`` is float, ``istop`` / ``estop`` are bool,
``pwm`` is float, ``vfd_enable`` is bool — so a flat ``False`` does
not produce useful values for the dashboard's SpindleCard.

This module is the spindle-specific equivalent of
:mod:`hardware.linuxcnc_mock`'s temperature simulation loop. It
maintains its own per-spindle target-RPM and ramp state, producing
sensible per-pin values for every poll.

Real hardware is untouched — when ``HAS_HAL and not USE_MOCK``,
:func:`hardware.hal_subscription_manager.read_pin` falls through to
``hal.get_value(pin_name)`` and reads the actual HAL signal. The
simulator only runs in mock mode (``USE_MOCK`` is true), so a live
machine with real HAL wiring is unaffected.

The simulator maintains a tiny per-spindle "last_read_actual"
cache so the RPM ramps smoothly toward target instead of jumping
on every read. A 0.1 s tick (matching :class:`HalSubscriptionManager`'s
``poll_interval``) at the integrator's typical 100 ms cadence gives
the dashboard roughly a ~2 second ramp from 0 to 12000 RPM, which
is realistic for a mid-sized VFD.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger("backend.hardware.spindle_pin_simulator")


# Realistic-ish ramp rate. A 12000 RPM spindle reaches target in
# roughly 2 seconds with this step size; the dashboard shows the
# bar climbing at a believable pace.
_RAMP_RPM_PER_TICK = 600
_AT_SPEED_TOLERANCE = 0.05  # 5 % — within this fraction of target, ``at_speed`` latches True
_IDLE_NOISE_RPM = 0          # when ``idle``, ``actual`` stays pinned at 0


# Per-spindle ramp state. Keyed by ``spindle_id`` so two spindles
# on the same machine ramp independently. The simulator owns this
# state — the service writes the operator's target via
# :func:`set_spindle_target` whenever a ``M3 S{x}`` / ``M4 S{x}`` /
# ``M5`` is dispatched. ``_last_actual`` decays toward ``_target``
# on every call.
_lock = threading.Lock()
_last_actual: Dict[str, float] = {}
_last_target: Dict[str, int] = {}


def set_spindle_target(spindle_id: str, target_rpm: int) -> None:
    """Update the simulator's target RPM for ``spindle_id``.

    Called by :class:`ToolsService.set_spindle_speed` whenever an
    operator action changes the spindle's commanded RPM (``M3 S{x}`` /
    ``M4 S{x}``) or stops it (``M5`` → ``target=0``).
    """
    with _lock:
        _last_target[spindle_id] = int(target_rpm or 0)


def _is_pin(pin_name: str, suffix: str) -> bool:
    return pin_name.endswith(f".{suffix}") or pin_name.endswith(suffix)


def read_spindle_pin(pin_name: str, spindle_id: str) -> Any:
    """Return a mock-mode spindle HAL pin value.

    Pin names mirror the :class:`backend.modules.tools.config_mapper.SpindleDigitalPins`
    fields. Unknown pins return ``0`` (a safe numeric default) so
    a misconfigured ``hardware.json`` cannot crash the dashboard.

    Parameters
    ----------
    pin_name:
        The HAL signal name (e.g. ``spindle.0.rpm-out``,
        ``spindle.0.at-speed``).
    spindle_id:
        The canonical ``spindle_digital`` tool id. Used to look up
        the operator's last action and the per-spindle ramp state.
    """
    # ``at_speed`` is the leading pin — once the spindle reaches
    # the operator's target, every subsequent read returns True
    # until the operator stops. Idle spindles never report at-speed.
    with _lock:
        target = float(_last_target.get(spindle_id, 0))
        # The simulator's "idle" state is implicit — when the
        # operator dispatched ``M5`` the service calls
        # :func:`set_spindle_target` with ``0``, which is the "stop"
        # command for the ramp. The service also tracks its own
        # ``_spindle_state[spindle_id]`` (idle / forward / reverse)
        # for the state machine; the simulator doesn't read that
        # directly — it reads the commanded RPM only. ``M3 S{x}``
        # and ``M4 S{x}`` both target ``x`` RPM; the service does
        # not differentiate direction here (the dashboard's
        # direction badge uses the service-tracked ``_spindle_state``
        # directly).
        current = _last_actual.get(spindle_id, 0.0)

        # Ramp toward target. Direction follows the gap.
        if current < target:
            current = min(target, current + _RAMP_RPM_PER_TICK)
        elif current > target:
            current = max(target, current - _RAMP_RPM_PER_TICK)
        _last_actual[spindle_id] = current
        is_running = target > 0

    # ``rpm_out`` is a float that mirrors ``actual_rpm`` rounded to
    # integer RPM. The SpindleCard renders this directly.
    if _is_pin(pin_name, "rpm-out") or _is_pin(pin_name, "rpm_out"):
        return int(round(current))

    # ``at_speed`` latches True when the spindle is running and
    # within 5 % of target. Idle never reports at-speed.
    if _is_pin(pin_name, "at-speed") or _is_pin(pin_name, "at_speed"):
        if not is_running:
            return False
        return abs(current - target) <= _AT_SPEED_TOLERANCE * target

    # Direction pins — these mirror the operator's last action. The
    # simulator doesn't have direct visibility into the service's
    # ``_spindle_state`` dict, so we infer direction from the
    # ``target`` value: a non-zero target means the spindle is
    # commanded to run (either direction). For ``forward`` /
    # ``reverse`` we use a simple heuristic — the more common case
    # is forward; the service stores the explicit ``forward`` /
    # ``reverse`` state separately for the state-machine check.
    if _is_pin(pin_name, "forward"):
        return is_running  # direction-agnostic while running
    if _is_pin(pin_name, "reverse"):
        return False  # direction-agnostic while running
    if _is_pin(pin_name, "on"):
        return is_running
    if _is_pin(pin_name, "vfd-enable") or _is_pin(pin_name, "vfd_enable"):
        return is_running

    # ``pwm`` (0.0–1.0) is the ratio of actual to target — a
    # coarse duty-cycle indicator the dashboard doesn't currently
    # render but the integrator's pyvcp panel may.
    if _is_pin(pin_name, "pwm"):
        if not is_running:
            return 0.0
        return current / max(target, 1.0)

    # ``istop`` and ``estop`` are alarms; the mock has no source of
    # errors so they stay False. A future revision could ramp these
    # under simulated fault conditions.
    if _is_pin(pin_name, "istop"):
        return False
    if _is_pin(pin_name, "estop"):
        return False

    # Unknown pin — safe numeric default so a misconfigured
    # ``hardware.json`` cannot crash the dashboard.
    logger.debug(
        "spindle_pin_simulator: unknown pin %r for spindle %r; "
        "returning 0",
        pin_name, spindle_id,
    )
    return 0


def reset_spindle_state(spindle_id: Optional[str] = None) -> None:
    """Clear cached ramp state — used by tests + lifecycle hooks.

    With no argument, clears every cached spindle (full reset). With
    an argument, clears only that spindle's cached ramp values so a
    fresh start ramps from 0 instead of inheriting the previous
    session's last-known value.
    """
    with _lock:
        if spindle_id is None:
            _last_actual.clear()
            _last_target.clear()
            return
        _last_actual.pop(spindle_id, None)
        _last_target.pop(spindle_id, None)


__all__ = [
    "read_spindle_pin",
    "set_spindle_target",
    "reset_spindle_state",
]
