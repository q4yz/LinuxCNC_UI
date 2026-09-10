"""RemoraStepperHalMapper — one axis (+ its joints, + a shared endstop) -> HalFragment.

`.agent/component/mcu_spi_remora.md` § 3-4, class B path. No stepgen,
no step/dir/enable HAL nets — those become firmware `config.txt`
entries instead (`FirmwareModuleRequest`), since the board owns the
pulses.
"""

from __future__ import annotations

from models.machineconfig.hal_fragment_models import PinRole
from services.halcompiler.components.RemoraStepperHalMapper import RemoraStepperHalMapper

X_JOINT = {
    "id": "stepper_x",
    "joint_number": 0,
    "step_pin": "mcu:PF13",
    "dir_pin": "mcu:!PF12",
    "enable_pin": "mcu:PF14",
}
X_AXIS = {"id": "x", "joint_numbers": [0], "endstop": "endstop_x"}
X_ENDSTOP = {"id": "endstop_x", "pin": "mcu:PC0"}


def test_position_loop_has_no_stepgen_timing():
    fragment = RemoraStepperHalMapper.to_fragment(X_AXIS, [X_JOINT], None)

    assert "setp remora.joint.0.scale [JOINT_0]SCALE" in fragment.setp
    assert "setp remora.joint.0.maxaccel [JOINT_0]STEPGEN_MAXACCEL" in fragment.setp
    assert not any("steplen" in s or "stepspace" in s or "dirhold" in s or "dirsetup" in s for s in fragment.setp)

    assert "net j0pos-cmd joint.0.motor-pos-cmd => remora.joint.0.pos-cmd" in fragment.nets
    assert "net j0pos-fb remora.joint.0.pos-fb => joint.0.motor-pos-fb" in fragment.nets


def test_enable_net_is_unconditional_unlike_class_a():
    """Every joint in the reference config wires `remora.joint.N.enable` —
    the board always owns an enable line for a module it loaded, so
    (unlike class A's optional pin) this is never conditional."""
    without = RemoraStepperHalMapper.to_fragment(X_AXIS, [{"id": "j", "joint_number": 0}], None)
    assert "net j0enable joint.0.amp-enable-out => remora.joint.0.enable" in without.nets


def test_step_dir_enable_never_become_hal_nets_or_pin_requests():
    fragment = RemoraStepperHalMapper.to_fragment(X_AXIS, [X_JOINT], None)
    assert not any(r.role in (PinRole.STEP, PinRole.DIR, PinRole.ENABLE) for r in fragment.requests)
    assert not any("stepgen" in n or "parport" in n for n in fragment.nets)


def test_joint_pins_become_one_firmware_stepgen_module():
    """Module shape verified against the real, working
    `machine_config/example/ender3/config.txt` — `"Type": "Stepgen"`
    (not "Stepper"), a `"Name"` field, and pins underscore-formatted
    (`"PF_13"`, not Klipper's `"PF13"`)."""
    fragment = RemoraStepperHalMapper.to_fragment(X_AXIS, [X_JOINT], None)
    assert len(fragment.firmware_modules) == 1

    request = fragment.firmware_modules[0]
    assert request.mcu_id == "mcu"
    assert request.module == {
        "Name": "stepper_x",
        "Thread": "Base",
        "Type": "Stepgen",
        "Comment": "stepper_x step generator",
        "Joint Number": 0,
        "Step Pin": "PF_13",
        "Direction Pin": "!PF_12",
        "Enable Pin": "PF_14",
    }


def test_dir_and_enable_pins_are_optional_in_the_firmware_module():
    joint = {"id": "stepper_x", "joint_number": 0, "step_pin": "mcu:PF13"}
    fragment = RemoraStepperHalMapper.to_fragment(X_AXIS, [joint], None)
    module = fragment.firmware_modules[0].module
    assert module["Step Pin"] == "PF_13"
    assert "Direction Pin" not in module
    assert "Enable Pin" not in module


def test_a_joint_with_no_step_pin_gets_no_firmware_module():
    joint = {"id": "stepper_x", "joint_number": 0}
    fragment = RemoraStepperHalMapper.to_fragment(X_AXIS, [joint], None)
    assert fragment.firmware_modules == []


def test_endstop_signal_is_named_from_the_endstop_not_the_axis():
    fragment = RemoraStepperHalMapper.to_fragment(X_AXIS, [X_JOINT], X_ENDSTOP)
    assert "net endstop_x-sw => joint.0.home-sw-in joint.0.neg-lim-sw-in" in fragment.nets

    request = next(r for r in fragment.requests if r.role is PinRole.ENDSTOP)
    assert request.signal == "endstop_x-sw"
    assert request.pin.pin_id == "PC0"


def test_endstop_wiring_targets_both_home_and_neg_lim_unlike_class_a():
    """`3Dprinter.hal`: `net X-stop remora.input.00 => joint.0.home-sw-in
    joint.0.neg-lim-sw-in` — genuinely different from the parport
    reference machine, which wires `home-sw-in` alone."""
    fragment = RemoraStepperHalMapper.to_fragment(X_AXIS, [X_JOINT], X_ENDSTOP)
    line = next(n for n in fragment.nets if "endstop_x-sw" in n)
    assert "joint.0.home-sw-in" in line
    assert "joint.0.neg-lim-sw-in" in line


def test_axis_with_no_endstop_emits_no_home_wiring():
    fragment = RemoraStepperHalMapper.to_fragment(X_AXIS, [X_JOINT], None)
    assert not any("home-sw" in n for n in fragment.nets)
    assert not any(r.role is PinRole.ENDSTOP for r in fragment.requests)


def test_a_dual_motor_axis_wires_the_shared_endstop_into_both_joints():
    y_axis = {"id": "y", "joint_numbers": [1, 2], "endstop": "endstop_y"}
    joints = [
        {"id": "stepper_y", "joint_number": 1, "step_pin": "mcu:PD0"},
        {"id": "stepper_y1", "joint_number": 2, "step_pin": "mcu:PD1"},
    ]
    endstop = {"id": "endstop_y", "pin": "mcu:PC1"}

    fragment = RemoraStepperHalMapper.to_fragment(y_axis, joints, endstop)

    assert "net endstop_y-sw => joint.1.home-sw-in joint.1.neg-lim-sw-in" in fragment.nets
    assert "net endstop_y-sw => joint.2.home-sw-in joint.2.neg-lim-sw-in" in fragment.nets
    assert sum(1 for r in fragment.requests if r.role is PinRole.ENDSTOP) == 1


def test_deadband_is_emitted_as_a_literal_value():
    """Real reference value, not invented — `ender3.hal` sets
    `setp remora.joint.2.deadband 0.005`."""
    joint = dict(X_JOINT, deadband=0.005)
    fragment = RemoraStepperHalMapper.to_fragment(X_AXIS, [joint], None)
    assert "setp remora.joint.0.deadband 0.005" in fragment.setp


def test_pgain_is_emitted_as_an_ini_var_reference_not_a_literal():
    """`ender3.hal` sets `setp remora.joint.3.pgain [JOINT_3]PGAIN` —
    an ini-var reference, matching every other tunable gain in this
    compiler (heater PID) being re-tunable without regenerating HAL."""
    joint = dict(X_JOINT, pgain=1.0)
    fragment = RemoraStepperHalMapper.to_fragment(X_AXIS, [joint], None)
    assert "setp remora.joint.0.pgain [JOINT_0]PGAIN" in fragment.setp
    assert not any("pgain 1.0" in s for s in fragment.setp)


def test_deadband_and_pgain_are_independently_optional():
    fragment = RemoraStepperHalMapper.to_fragment(X_AXIS, [X_JOINT], None)
    assert not any("deadband" in s for s in fragment.setp)
    assert not any("pgain" in s for s in fragment.setp)
