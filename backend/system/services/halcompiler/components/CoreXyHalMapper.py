"""``[machine] kinematics: corexy`` -> the CoreXY math in HAL, between
LinuxCNC's joints and the Remora step generators
(`.agent/component/corexy.md`).

LinuxCNC keeps ``trivkins`` with Cartesian joints X and Y — homing,
endstops and soft limits stay per axis — and HAL turns them into the two
belt motors, Klipper's convention (``[stepper_x]`` = motor A,
``[stepper_y]`` = motor B):

    command   A = X + Y      B = X - Y
    feedback  X = (A + B)/2  Y = (A - B)/2

Stock ``sum2`` components, no ``corexykins``. Motor A is the Remora joint
of the X joint number, motor B that of Y; their ``pos-cmd`` / ``pos-fb``
nets replace `RemoraStepperHalMapper`'s direct ones.

With input shaping / skew (``shaped``: `JointShapeHalMapper` on the X / Y
joints) the shapers sit *before* the mixing — they shape the Cartesian X
and Y, as Klipper does on CoreXY — and get the recovered X / Y back::

    joint.X.motor-pos-cmd -> shape-jX -> j<X>pos-cmd-shaped -> A, B -> motors
    motors -> X, Y feedback -> j<X>pos-fb -> shape-jX -> joint.X.motor-pos-fb

The mixing is linear, so a stepgen error on A / B maps back to the X / Y
error the shaper expects.
"""

from __future__ import annotations

from models.machineconfig.HalFragmentModels import SERVO_THREAD, Addf, HalFragment

A_CMD, B_CMD, X_FB, Y_FB = "corexy-a", "corexy-b", "corexy-x", "corexy-y"


class CoreXyHalMapper:
    @staticmethod
    def to_fragment(x: int, y: int, shaped: bool = False) -> HalFragment:
        """``x`` / ``y``: the joint numbers of the X and Y axes. ``shaped``:
        their ``jointshape`` instances feed the mixing and take its feedback."""
        sums = (A_CMD, B_CMD, X_FB, Y_FB)
        if shaped:
            command = [
                f"net j{x}pos-cmd-shaped => {A_CMD}.in0 {B_CMD}.in0",
                f"net j{y}pos-cmd-shaped => {A_CMD}.in1 {B_CMD}.in1",
            ]
            feedback = [f"net j{x}pos-fb {X_FB}.out", f"net j{y}pos-fb {Y_FB}.out"]
        else:
            command = [
                f"net j{x}pos-cmd joint.{x}.motor-pos-cmd => {A_CMD}.in0 {B_CMD}.in0",
                f"net j{y}pos-cmd joint.{y}.motor-pos-cmd => {A_CMD}.in1 {B_CMD}.in1",
            ]
            feedback = [
                f"net j{x}pos-fb {X_FB}.out => joint.{x}.motor-pos-fb",
                f"net j{y}pos-fb {Y_FB}.out => joint.{y}.motor-pos-fb",
            ]
        return HalFragment(
            loadrt=[f"loadrt sum2 names={name}" for name in sums],
            # feedback right after remora.read (0), so motion / the shapers
            # see this period's position; the motor commands after motion
            # and the shapers (2), before remora.write (3)
            addf=[Addf(X_FB, SERVO_THREAD, order=0), Addf(Y_FB, SERVO_THREAD, order=0),
                  Addf(A_CMD, SERVO_THREAD, order=2), Addf(B_CMD, SERVO_THREAD, order=2)],
            setp=[
                f"setp {B_CMD}.gain1 -1",
                f"setp {X_FB}.gain0 0.5",
                f"setp {X_FB}.gain1 0.5",
                f"setp {Y_FB}.gain0 0.5",
                f"setp {Y_FB}.gain1 -0.5",
            ],
            nets=[
                *command,
                f"net corexy-a-cmd {A_CMD}.out => remora.joint.{x}.pos-cmd",
                f"net corexy-b-cmd {B_CMD}.out => remora.joint.{y}.pos-cmd",
                f"net corexy-a-fb remora.joint.{x}.pos-fb => {X_FB}.in0 {Y_FB}.in0",
                f"net corexy-b-fb remora.joint.{y}.pos-fb => {X_FB}.in1 {Y_FB}.in1",
                *feedback,
            ],
        )


__all__ = ["CoreXyHalMapper"]
