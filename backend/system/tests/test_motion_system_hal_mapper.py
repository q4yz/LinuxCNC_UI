"""MotionSystemHalMapper — the [KINS]/[EMCMOT] loadrt and, on class A, `stepgen`."""

from __future__ import annotations

from models.machineconfig.hal_fragment_models import BASE_THREAD, SERVO_THREAD
from models.machineconfig.pin_models import CapabilityClass
from services.halcompiler.components.MotionSystemHalMapper import MotionSystemHalMapper


def test_kinematics_and_emcmot_are_always_loaded():
    fragment = MotionSystemHalMapper.to_fragment(4, CapabilityClass.STEP_DIR)
    assert "loadrt [KINS]KINEMATICS" in fragment.loadrt
    assert any("EMCMOT" in line for line in fragment.loadrt)


def test_motion_functions_run_on_the_servo_thread_regardless_of_class():
    fragment = MotionSystemHalMapper.to_fragment(4, CapabilityClass.POSITION)
    funcs = {(a.func, a.thread) for a in fragment.addf}
    assert ("motion-command-handler", SERVO_THREAD) in funcs
    assert ("motion-controller", SERVO_THREAD) in funcs


def test_class_a_gets_stepgen_sized_to_the_joint_count():
    fragment = MotionSystemHalMapper.to_fragment(4, CapabilityClass.STEP_DIR)
    assert "loadrt stepgen step_type=0,0,0,0" in fragment.loadrt

    funcs = {(a.func, a.thread) for a in fragment.addf}
    assert ("stepgen.make-pulses", BASE_THREAD) in funcs
    assert ("stepgen.capture-position", SERVO_THREAD) in funcs
    assert ("stepgen.update-freq", SERVO_THREAD) in funcs


def test_class_b_gets_no_stepgen_at_all():
    """Remora/EtherCAT: the board makes the pulses, not software stepgen."""
    fragment = MotionSystemHalMapper.to_fragment(4, CapabilityClass.POSITION)
    assert not any("stepgen" in line for line in fragment.loadrt)
    assert not any("stepgen" in a.func for a in fragment.addf)


def test_addf_role_ordering_matches_the_documented_tiers():
    """README § 4: base (read -> make-pulses -> write -> reset), servo (read -> motion -> write).

    This mapper only contributes the make-pulses/capture-position/
    update-freq/motion-* entries — read/write/reset come from the MCU
    router — but its own three-way relative order (capture-position
    before the motion functions, motion functions before
    update-freq) must already be correct before the renderer sorts
    the full machine-wide list.
    """
    fragment = MotionSystemHalMapper.to_fragment(4, CapabilityClass.STEP_DIR)
    servo = {a.func: a.order for a in fragment.addf if a.thread == SERVO_THREAD}
    assert servo["stepgen.capture-position"] < servo["motion-command-handler"]
    assert servo["motion-command-handler"] < servo["stepgen.update-freq"]
    assert servo["motion-controller"] < servo["stepgen.update-freq"]
