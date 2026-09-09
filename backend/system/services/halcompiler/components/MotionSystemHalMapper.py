"""The machine-wide motion loop: kinematics, `motmod`, and (class A)
software `stepgen` sized to the joint count.

Not owned by any one component or MCU — `loadrt stepgen
step_type=0,0,...` needs the total joint count, and
`motion-command-handler` / `motion-controller` exist regardless of
which MCU carries which joint. README § 4 calls this kind of thing a
"global concern" for the assembler; kept here as its own small mapper
instead, so it stays independently testable rather than folded into
assembler logic.
"""

from __future__ import annotations

from models.machineconfig.hal_fragment_models import (
    BASE_THREAD,
    SERVO_THREAD,
    Addf,
    HalFragment,
)
from models.machineconfig.pin_models import CapabilityClass

#: `stepgen` step_type 0 = step/dir (the only type this compiler emits).
_STEP_DIR_TYPE = "0"


class MotionSystemHalMapper:
    """`[KINS]`/`[EMCMOT]` loadrt plus, on class A, the `stepgen` bank."""

    @staticmethod
    def to_fragment(joint_count: int, capability_class: CapabilityClass) -> HalFragment:
        fragment = HalFragment(
            loadrt=[
                "loadrt [KINS]KINEMATICS",
                "loadrt [EMCMOT]EMCMOT base_period_nsec=[EMCMOT]BASE_PERIOD "
                "servo_period_nsec=[EMCMOT]SERVO_PERIOD num_joints=[KINS]JOINTS",
            ],
            addf=[
                Addf("motion-command-handler", SERVO_THREAD, order=1),
                Addf("motion-controller", SERVO_THREAD, order=1),
            ],
        )

        # Only machines that actually drive joints from software stepgen
        # get the bank — a joint-less machine (a VFD-only spindle
        # controller) has no class-A hardware, and an unused stepgen
        # would misstate what makes its pulses.
        if capability_class is CapabilityClass.STEP_DIR and joint_count > 0:
            step_types = ",".join([_STEP_DIR_TYPE] * joint_count) if joint_count else _STEP_DIR_TYPE
            fragment.loadrt.append(f"loadrt stepgen step_type={step_types}")
            fragment.addf.extend(
                [
                    Addf("stepgen.make-pulses", BASE_THREAD, order=1),
                    Addf("stepgen.capture-position", SERVO_THREAD, order=0),
                    Addf("stepgen.update-freq", SERVO_THREAD, order=2),
                ]
            )

        return fragment


__all__ = ["MotionSystemHalMapper"]
