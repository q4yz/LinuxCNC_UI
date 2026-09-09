"""StepperHalMapper — one axis (+ its joints, + a shared endstop) -> HalFragment.

`.agent/component/stepper.md` § 3, class A path.
"""

from __future__ import annotations

from models.machineconfig.hal_fragment_models import PinRole
from services.halcompiler.components.StepperHalMapper import StepperHalMapper

X_JOINT = {"id": "stepper_x", "joint_number": 0, "step_pin": "mcu:08", "dir_pin": "mcu:!09"}
X_AXIS = {"id": "x", "joint_numbers": [0], "endstop": "endstop_xz"}
XZ_ENDSTOP = {"id": "endstop_xz", "pin": "mcu:!13"}


def test_per_joint_position_loop_and_stepgen_config():
    fragment = StepperHalMapper.to_fragment(X_AXIS, [X_JOINT], None)

    assert "setp stepgen.0.position-scale [JOINT_0]SCALE" in fragment.setp
    assert "setp stepgen.0.steplen 1" in fragment.setp
    assert "setp stepgen.0.stepspace 0" in fragment.setp
    assert "setp stepgen.0.dirhold 39000" in fragment.setp
    assert "setp stepgen.0.dirsetup 39000" in fragment.setp
    assert "setp stepgen.0.maxaccel [JOINT_0]STEPGEN_MAXACCEL" in fragment.setp

    assert "net xpos-cmd joint.0.motor-pos-cmd => stepgen.0.position-cmd" in fragment.nets
    assert "net xpos-fb stepgen.0.position-fb => joint.0.motor-pos-fb" in fragment.nets


def test_step_and_dir_are_exported_as_requests_with_correct_invert():
    fragment = StepperHalMapper.to_fragment(X_AXIS, [X_JOINT], None)

    assert "net stepper_x-step <= stepgen.0.step" in fragment.nets
    assert "net stepper_x-dir <= stepgen.0.dir" in fragment.nets

    by_role = {r.role: r for r in fragment.requests}
    assert by_role[PinRole.STEP].signal == "stepper_x-step"
    assert by_role[PinRole.STEP].pin.pin_id == "08"
    assert by_role[PinRole.STEP].pin.invert is False

    assert by_role[PinRole.DIR].signal == "stepper_x-dir"
    assert by_role[PinRole.DIR].pin.pin_id == "09"
    assert by_role[PinRole.DIR].pin.invert is True


def test_enable_is_optional_and_only_exported_when_present():
    without = StepperHalMapper.to_fragment(X_AXIS, [X_JOINT], None)
    assert not any(r.role is PinRole.ENABLE for r in without.requests)
    assert not any("enable" in n for n in without.nets)

    joint = dict(X_JOINT, enable_pin="mcu:!14")
    withit = StepperHalMapper.to_fragment(X_AXIS, [joint], None)
    assert "net stepper_x-enable joint.0.amp-enable-out => stepgen.0.enable" in withit.nets
    request = next(r for r in withit.requests if r.role is PinRole.ENABLE)
    assert request.signal == "stepper_x-enable" and request.pin.pin_id == "14"


def test_endstop_signal_is_named_from_the_endstop_not_the_axis():
    """Two axes sharing one endstop must produce the SAME signal name.

    PrintNC-WEBGUI's real Machine.hal wires both X and Z off one
    physical switch ("home-xz") — naming the signal after the axis
    instead of the endstop would give each axis its own signal, and
    two `net <sig> <= parport...-in` writers for one physical pin is
    a HAL load error.
    """
    x_fragment = StepperHalMapper.to_fragment(X_AXIS, [X_JOINT], XZ_ENDSTOP)
    z_axis = {"id": "z", "joint_numbers": [3], "endstop": "endstop_xz"}
    z_joint = {"id": "stepper_z", "joint_number": 3, "step_pin": "mcu:06", "dir_pin": "mcu:07"}
    z_fragment = StepperHalMapper.to_fragment(z_axis, [z_joint], XZ_ENDSTOP)

    assert "net endstop_xz-sw => joint.0.home-sw-in" in x_fragment.nets
    assert "net endstop_xz-sw => joint.3.home-sw-in" in z_fragment.nets

    x_req = next(r for r in x_fragment.requests if r.role is PinRole.ENDSTOP)
    z_req = next(r for r in z_fragment.requests if r.role is PinRole.ENDSTOP)
    assert x_req.signal == z_req.signal == "endstop_xz-sw"
    assert x_req.pin.pin_id == z_req.pin.pin_id == "13"
    assert x_req.pin.invert is True


def test_axis_with_no_endstop_emits_no_home_wiring():
    fragment = StepperHalMapper.to_fragment(X_AXIS, [X_JOINT], None)
    assert not any("home-sw" in n for n in fragment.nets)
    assert not any(r.role is PinRole.ENDSTOP for r in fragment.requests)


def test_a_dual_motor_axis_wires_the_shared_endstop_into_both_joints():
    y_axis = {"id": "y", "joint_numbers": [1, 2], "endstop": "endstop_y"}
    joints = [
        {"id": "stepper_y", "joint_number": 1, "step_pin": "mcu:02", "dir_pin": "mcu:!03"},
        {"id": "stepper_y1", "joint_number": 2, "step_pin": "mcu:04", "dir_pin": "mcu:!05"},
    ]
    endstop = {"id": "endstop_y", "pin": "mcu:12"}

    fragment = StepperHalMapper.to_fragment(y_axis, joints, endstop)

    assert "net endstop_y-sw => joint.1.home-sw-in" in fragment.nets
    assert "net endstop_y-sw => joint.2.home-sw-in" in fragment.nets
    # One writer only, however many joints share it.
    assert sum(1 for r in fragment.requests if r.role is PinRole.ENDSTOP) == 1
