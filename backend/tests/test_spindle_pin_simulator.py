"""Tests for the OOP spindle-pin mock simulator.

Pins the contract the dashboard's SpindleCard relies on:

* Idle spindles return ``actual=0`` and ``is_connected=False``.
* Running spindles ramp ``actual`` toward the operator's target.
* ``at_speed`` latches True within 5 % of target.
* Unknown pins return a safe default (no crash on a misconfigured
  ``hardware.json``).
"""
from __future__ import annotations

import pytest

from hardware.mock.linuxcnc_mock import mock_system, hal
from hardware.mock.test_helpers.mock_helpers import reset_simulator_state
from hardware.mock.tools.mock_spindle_digital import MockSpindleDigital


@pytest.fixture(autouse=True)
def _reset_simulator_state():
    """Reset the orchestrator and load fresh spindles before each test."""
    mock_system.internal_hal._components.clear()

    # Register our OOP components
    mock_system.internal_hal.register_component(MockSpindleDigital("spindle_main"))
    mock_system.internal_hal.register_component(MockSpindleDigital("spindle_extruder"))

    yield

    mock_system.internal_hal._components.clear()


# ────────────────────────────────────────────────────────────────────── #
# Idle                                                                    #
# ────────────────────────────────────────────────────────────────────── #


def test_idle_rpm_out_is_zero():
    hal.set_p("spindle.0.speed-out", 0)
    mock_system.internal_hal.update() # Tick time forward!

    val = hal.get_p("spindle.0.rpm-out")
    assert val == 0


def test_idle_at_speed_is_false():
    reset_simulator_state()
    hal.set_p("spindle.0.speed-out", 0)
    mock_system.internal_hal.update()

    assert hal.get_p("spindle.0.at-speed") is False


def test_idle_vfd_enable_is_false():
    hal.set_p("spindle.0.speed-out", 0)
    mock_system.internal_hal.update()

    assert hal.get_p("spindle.0.vfd-enable") is False


# ────────────────────────────────────────────────────────────────────── #
# Running — ramp behaviour                                                #
# ────────────────────────────────────────────────────────────────────── #


def test_running_rpm_out_ramps_toward_target():
    hal.set_p("spindle.0.speed-out", 12000)

    # First tick
    mock_system.internal_hal.update()
    first = hal.get_p("spindle.0.rpm-out")

    # Should be at the first ramp step (usually 600)
    assert first > 0 and first < 12000

    # Subsequent reads ramp toward 12000.
    samples = []
    for _ in range(30):
        mock_system.update()
        samples.append(hal.get_p("spindle.0.rpm-out"))

    # Monotonic non-decreasing while ramping up.
    assert all(b >= a for a, b in zip(samples, samples[1:]))
    # Reaches target by the time we've ticked enough times.
    assert samples[-1] == 12000


def test_at_speed_latches_true_within_five_percent():
    hal.set_p("spindle.0.speed-out", 12000)

    # Drive enough ticks that we ramp all the way to 12000.
    for _ in range(30):
        mock_system.internal_hal.update()

    # Now at-speed should latch True.
    assert hal.get_p("spindle.0.at-speed") is True


def test_at_speed_stays_false_during_ramp():
    hal.set_p("spindle.0.speed-out", 12000)

    # First read — we're at the first ramp step, far below target.
    mock_system.internal_hal.update()
    assert hal.get_p("spindle.0.at-speed") is False


# ────────────────────────────────────────────────────────────────────── #
# Engagement / control pins                                               #
# ────────────────────────────────────────────────────────────────────── #


def test_vfd_enable_true_when_running():
    hal.set_p("spindle.0.speed-out", 12000)
    mock_system.internal_hal.update()
    assert hal.get_p("spindle.0.vfd-enable") is True


def test_vfd_enable_true_when_running_pin_variant():
    """Pin name ``vfd_enable`` (underscore) is matched as well as ``vfd-enable``."""
    hal.set_p("spindle.0.speed-out", 12000)
    mock_system.internal_hal.update()
    assert hal.get_p("spindle.0.vfd_enable") is True


def test_vfd_enable_false_when_idle():
    hal.set_p("spindle.0.speed-out", 0)
    mock_system.internal_hal.update()
    assert hal.get_p("spindle.0.vfd-enable") is False


def test_vfd_enable_false_when_idle_pin_variant():
    """Pin name ``vfd_enable`` (underscore) is matched as well as ``vfd-enable``."""
    hal.set_p("spindle.0.speed-out", 0)
    mock_system.internal_hal.update()
    assert hal.get_p("spindle.0.vfd_enable") is False


def test_pwm_returns_zero_when_idle():
    hal.set_p("spindle.0.speed-out", 0)
    mock_system.internal_hal.update()
    assert hal.get_p("spindle.0.pwm") == 0.0


def test_pwm_returns_ratio_when_running():
    hal.set_p("spindle.0.speed-out", 12000)

    # Tick until we reach a known fraction of target.
    for _ in range(10):
        mock_system.internal_hal.update()

    pwm = hal.get_p("spindle.0.pwm")
    # 10 ticks × ~600 RPM/tick = ~6000 RPM; ratio is roughly 0.5.
    assert 0.4 < pwm < 0.6


# ────────────────────────────────────────────────────────────────────── #
# Resilience                                                              #
# ────────────────────────────────────────────────────────────────────── #


def test_unknown_pin_returns_safe_default():
    # A typo in ``hardware.json`` should not crash the dashboard
    val = hal.get_p("spindle.0.this-pin-does-not-exist")
    assert val == 0


def test_alarm_pins_stay_false_in_idle():
    hal.set_p("spindle.0.speed-out", 12000)
    mock_system.internal_hal.update()
    assert hal.get_p("spindle.0.istop") is False
    assert hal.get_p("spindle.0.estop") is False


def test_two_spindles_have_independent_ramp_state():
    """Setting target for spindle A does not affect spindle B."""
    hal.set_p("spindle_main.speed-out", 12000)
    hal.set_p("spindle_extruder.speed-out", 0)

    # Tick the whole machine forward
    for _ in range(30):
        mock_system.internal_hal.update()

    main_rpm = hal.get_p("spindle_main.rpm-out")
    assert main_rpm == 12000

    # spindle_extruder stays at 0
    extruder_rpm = hal.get_p("spindle_extruder.rpm-out")
    assert extruder_rpm == 0


def test_reset_spindle_state_for_one_spindle_only():
    """Replacing one component shouldn't reset the others."""
    hal.set_p("spindle_main.speed-out", 12000)
    hal.set_p("spindle_extruder.speed-out", 6000)

    # Ramp both.
    for _ in range(30):
        mock_system.internal_hal.update()

    # Re-register ONLY the main spindle (this effectively resets it)
    mock_system.internal_hal._components = [
        c for c in mock_system.internal_hal._components
        if getattr(c, "id", None) != "spindle_main"
    ]
    mock_system.register_component(MockSpindleDigital("spindle_main"))

    mock_system.internal_hal.update()

    # spindle_main is reset to 0; spindle_extruder stays at target.
    assert hal.get_p("spindle_main.rpm-out") == 0
    assert hal.get_p("spindle_extruder.rpm-out") == 6000