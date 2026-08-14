"""Tests for the spindle-pin mock simulator.

Pins the contract the dashboard's SpindleCard relies on:

* Idle spindles return ``actual=0`` and ``is_connected=False``.
* Running spindles ramp ``actual`` toward the operator's target.
* ``at_speed`` latches True within 5 % of target.
* Unknown pins return a safe default (no crash on a misconfigured
  ``hardware.json``).
"""
from __future__ import annotations

import pytest

from hardware import spindle_pin_simulator as sim


@pytest.fixture(autouse=True)
def _reset_simulator_state():
    """Reset the simulator's cached ramp state between tests.

    The simulator owns a per-spindle "last_actual" / "last_target"
    cache. A test that runs first with target=12000 leaves the cache
    at the ramp endpoint; a second test with target=0 would start
    mid-ramp. Reset before each test so each starts at 0.
    """
    sim.reset_spindle_state()
    yield
    sim.reset_spindle_state()


# ────────────────────────────────────────────────────────────────────── #
# Idle                                                                    #
# ────────────────────────────────────────────────────────────────────── #


def test_idle_rpm_out_is_zero():
    sim.set_spindle_target("spindle_main", 0)
    # ``actual`` is the canonical "stop the ramp here" state — a
    # spindle that was just turned off should drop to 0 within one
    # tick. The simulator pulls the target from its own cache, so
    # calling read_spindle_pin without setting a target first leaves
    # the cache at 0 too.
    val = sim.read_spindle_pin("spindle.0.rpm-out", "spindle_main")
    assert val == 0


def test_idle_at_speed_is_false():
    sim.set_spindle_target("spindle_main", 0)
    assert sim.read_spindle_pin("spindle.0.at-speed", "spindle_main") is False


def test_idle_vfd_enable_is_false():
    sim.set_spindle_target("spindle_main", 0)
    assert (
        sim.read_spindle_pin("spindle.0.vfd-enable", "spindle_main") is False
    )


# ────────────────────────────────────────────────────────────────────── #
# Running — ramp behaviour                                                #
# ────────────────────────────────────────────────────────────────────── #


def test_running_rpm_out_ramps_toward_target():
    sim.set_spindle_target("spindle_main", 12000)
    # First read after setting target should be at ``_RAMP_RPM_PER_TICK``
    # (the simulator ticks up by one ramp-step per call).
    first = sim.read_spindle_pin("spindle.0.rpm-out", "spindle_main")
    assert first == sim._RAMP_RPM_PER_TICK

    # Subsequent reads ramp toward 12000.
    samples = [
        sim.read_spindle_pin("spindle.0.rpm-out", "spindle_main")
        for _ in range(30)
    ]
    # Monotonic non-decreasing while ramping up.
    assert all(b >= a for a, b in zip(samples, samples[1:]))
    # Reaches target by the time we've ticked enough times.
    assert samples[-1] == 12000


def test_at_speed_latches_true_within_five_percent():
    sim.set_spindle_target("spindle_main", 12000)
    # Drive enough ticks that we ramp all the way to 12000.
    for _ in range(30):
        sim.read_spindle_pin("spindle.0.rpm-out", "spindle_main")
    # Now at-speed should latch True.
    assert (
        sim.read_spindle_pin("spindle.0.at-speed", "spindle_main") is True
    )


def test_at_speed_stays_false_during_ramp():
    sim.set_spindle_target("spindle_main", 12000)
    # First read — we're at the first ramp step, far below target.
    sim.read_spindle_pin("spindle.0.rpm-out", "spindle_main")
    assert (
        sim.read_spindle_pin("spindle.0.at-speed", "spindle_main") is False
    )


# ────────────────────────────────────────────────────────────────────── #
# Engagement / control pins                                               #
# ────────────────────────────────────────────────────────────────────── #


def test_vfd_enable_true_when_running():
    sim.set_spindle_target("spindle_main", 12000)
    assert (
        sim.read_spindle_pin("spindle.0.vfd-enable", "spindle_main") is True
    )


def test_vfd_enable_true_when_running_pin_variant():
    """Pin name ``vfd_enable`` (underscore) is matched as well as ``vfd-enable``."""
    sim.set_spindle_target("spindle_main", 12000)
    assert (
        sim.read_spindle_pin("spindle.0.vfd_enable", "spindle_main") is True
    )


def test_vfd_enable_true_when_running():
    pass
    sim.set_spindle_target("spindle_main", 12000)
    assert (
        sim.read_spindle_pin("spindle.0.vfd-enable", "spindle_main") is True
    )


def test_vfd_enable_false_when_idle():
    sim.set_spindle_target("spindle_main", 0)
    assert (
        sim.read_spindle_pin("spindle.0.vfd-enable", "spindle_main") is False
    )


def test_vfd_enable_false_when_idle_pin_variant():
    """Pin name ``vfd_enable`` (underscore) is matched as well as ``vfd-enable``."""
    sim.set_spindle_target("spindle_main", 0)
    assert (
        sim.read_spindle_pin("spindle.0.vfd_enable", "spindle_main") is False
    )


def test_pwm_returns_zero_when_idle():
    sim.set_spindle_target("spindle_main", 0)
    assert sim.read_spindle_pin("spindle.0.pwm", "spindle_main") == 0.0


def test_pwm_returns_ratio_when_running():
    sim.set_spindle_target("spindle_main", 12000)
    # Tick until we reach a known fraction of target.
    for _ in range(10):
        sim.read_spindle_pin("spindle.0.rpm-out", "spindle_main")
    pwm = sim.read_spindle_pin("spindle.0.pwm", "spindle_main")
    # 10 ticks × 600 RPM/tick = 6000 RPM; ratio is 6000/12000 = 0.5.
    assert 0.4 < pwm < 0.6


# ────────────────────────────────────────────────────────────────────── #
# Resilience                                                              #
# ────────────────────────────────────────────────────────────────────── #


def test_unknown_pin_returns_safe_default():
    # A typo in ``hardware.json`` should not crash the dashboard —
    # the simulator returns ``0`` so the dashboard renders an "n/a"
    # cell rather than a 5xx.
    val = sim.read_spindle_pin(
        "spindle.0.this-pin-does-not-exist", "spindle_main"
    )
    assert val == 0


def test_alarm_pins_stay_false_in_idle():
    # ``istop`` and ``estop`` are alarms. The mock has no source of
    # errors so they stay False. Pin the contract so a future
    # revision cannot silently flip them.
    sim.set_spindle_target("spindle_main", 12000)
    assert sim.read_spindle_pin("spindle.0.istop", "spindle_main") is False
    assert sim.read_spindle_pin("spindle.0.estop", "spindle_main") is False


def test_two_spindles_have_independent_ramp_state():
    """``set_spindle_target`` for spindle A does not affect spindle B.

    The cache is keyed by ``spindle_id``; a regression that drops
    the key would let one spindle's ramp leak into another.
    """
    sim.set_spindle_target("spindle_main", 12000)
    sim.set_spindle_target("spindle_extruder", 0)

    # Tick spindle_main a bunch — should reach target.
    for _ in range(30):
        sim.read_spindle_pin("spindle_main.rpm-out", "spindle_main")
    main_rpm = sim.read_spindle_pin(
        "spindle_main.rpm-out", "spindle_main"
    )
    assert main_rpm == 12000

    # spindle_extruder stays at 0 — different spindle, different cache.
    extruder_rpm = sim.read_spindle_pin(
        "spindle_extruder.rpm-out", "spindle_extruder"
    )
    assert extruder_rpm == 0


def test_reset_spindle_state_for_one_spindle_only():
    """``reset_spindle_state(spindle_id)`` clears one entry, not all."""
    sim.set_spindle_target("spindle_main", 12000)
    sim.set_spindle_target("spindle_extruder", 6000)
    # Ramp both.
    for _ in range(30):
        sim.read_spindle_pin("spindle_main.rpm-out", "spindle_main")
        sim.read_spindle_pin("spindle_extruder.rpm-out", "spindle_extruder")

    sim.reset_spindle_state("spindle_main")

    # spindle_main resets to 0; spindle_extruder stays at target.
    assert sim.read_spindle_pin(
        "spindle_main.rpm-out", "spindle_main"
    ) == 0
    assert sim.read_spindle_pin(
        "spindle_extruder.rpm-out", "spindle_extruder"
    ) == 6000
