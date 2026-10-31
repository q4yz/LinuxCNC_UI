"""`[bed_mesh]` -> the Remora `compensation` component in `machine.hal`
(`.agent/component/bed_mesh.md`).

`compensation` (Remora-m8p `LinuxCNC/Components/Compensation`, installed
as `remora-compensation`) reads the active mesh file — `x y z` lines on a
regular grid — interpolates it and turns the Z offset under the current
X/Y position into `compensation.counts` (s32, 0.001 mm per count).

Z has one external offset input (`axis.z.eoffset-counts`) and Pause &
Inspect lifts Z through it too, so both are summed here in machine units:

    compensation.counts -> s32->float ------------------> sum2.in1 (gain 1)
    webgui.inspect-z-lift -> bit->float (webgui file) --> sum2.in0 (gain 1000)
    sum2.out -> float->s32 -> axis.z.eoffset-counts       (scale 0.001 mm)

The webgui / halui half (positions, enable, the lift) is in
`BedMeshWebguiMapper` / `PauseInspectWebguiMapper`: those pins only exist
once `webgui` / `halui` run.
"""

from __future__ import annotations

from models.machineconfig.HalFragmentModels import SERVO_THREAD, Addf, HalFragment

#: The installed component (`scripts/install_hal_components.sh`).
COMPENSATION_COMMAND = "python3 /usr/local/bin/remora-compensation"
#: `griddata` method: `nearest`, `linear` or `cubic` (the component default).
INTERPOLATION = "cubic"
#: 0.001 mm per external offset count (the component's own `scale`).
COUNTS_PER_MM = 1000

LIFT_FLOAT = "z-lift-float"
MESH_FLOAT = "bed-mesh-float"
EOFFSET_SUM = "z-eoffset-sum"
EOFFSET_COUNTS = "z-eoffset-counts"


class BedMeshHalMapper:
    @staticmethod
    def to_fragment(active_mesh_file: str) -> HalFragment:
        comps = (
            ("conv_bit_float", LIFT_FLOAT),
            ("conv_s32_float", MESH_FLOAT),
            ("sum2", EOFFSET_SUM),
            ("conv_float_s32", EOFFSET_COUNTS),
        )
        return HalFragment(
            loadusr=[
                f"loadusr -Wn compensation {COMPENSATION_COMMAND} {active_mesh_file} {INTERPOLATION}"
            ],
            loadrt=[f"loadrt {component} names={name}" for component, name in comps],
            addf=[Addf(name, SERVO_THREAD, order=1) for _component, name in comps],
            setp=[
                "setp compensation.fade-height 0",
                f"setp {EOFFSET_SUM}.gain0 {COUNTS_PER_MM}",
                f"setp {EOFFSET_SUM}.gain1 1",
            ],
            nets=[
                f"net bed-mesh-counts compensation.counts => {MESH_FLOAT}.in",
                f"net bed-mesh-offset {MESH_FLOAT}.out => {EOFFSET_SUM}.in1",
                f"net z-lift-counts {LIFT_FLOAT}.out => {EOFFSET_SUM}.in0",
                f"net z-eoffset-total {EOFFSET_SUM}.out => {EOFFSET_COUNTS}.in",
                f"net z-eoffset-counts {EOFFSET_COUNTS}.out => axis.z.eoffset-counts",
                "net bed-mesh-eoffset axis.z.eoffset => compensation.eoffset",
                "net bed-mesh-limited motion.eoffset-limited => compensation.eoffset-limited",
            ],
        )


__all__ = ["BedMeshHalMapper", "COUNTS_PER_MM", "LIFT_FLOAT"]
