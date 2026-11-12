"""`[probe]` + `[tool_length_sensor]` -> :class:`HalFragment` (`.agent/component/probe.md`).

LinuxCNC has exactly one probe input, `motion.probe-input` (a core
motion pin — no `loadrt`). A machine can have two switches that should
trigger it: the touch probe and the tool-length sensor (tool setter).
Both are owned here because they share that one pin.

The touch probe only reaches `motion.probe-input` during a probing move
(G38.x, `motion.motion-type` 5 = EMC_MOTION_TYPE_PROBING). LinuxCNC
aborts any other move during which the probe input switches on ("Probe
tripped during non-probe move.", `control.c`) — and an inductive probe
switches on near the bed, so the first layer of every print would abort
it, as would homing Z on the probe (``z_virtual_endstop``)::

    loadrt conv_s32_float names=probe-mtype
    loadrt wcomp names=probe-probing
    loadrt and2 names=probe-gate
    setp probe-probing.min 4.5
    setp probe-probing.max 5.5
    net probe-motion-type motion.motion-type => probe-mtype.in
    net probe-motion-type-f probe-mtype.out => probe-probing.in
    net probe-allowed probe-probing.out => probe-gate.in1
    net probe-in => probe-gate.in0
    net probe-gated probe-gate.out => motion.probe-input

`probe-gate.in0` carries the probe's own state, for macros that check it
(``#<_hal[probe-gate.in0]>``). The tool-length sensor stays ungated: on a
mill, a tool setter that trips during a normal move is a crash, and
LinuxCNC's abort is what should happen. With both declared, an `or2`
merges the gated probe and the sensor::

    loadrt or2 names=probe-or
    net probe-gated probe-gate.out => probe-or.in0
    net tool-length-sensor-in => probe-or.in1
    net probe-or-out probe-or.out => motion.probe-input

NC/NO is the pin's own `!` in the `.cfg`, handled per input by the MCU
router that binds the :class:`PinRequest` (`parport…-in-not`,
`remora.input.NN.not`, an explicit `not` stage for vfdmod) — so the
two switches can have opposite polarities and the OR always sees
"1 = triggered".

Verified against the real reference machine,
`machine_config/example/PrintNC-WEBGUI/Machine.hal` (line 93):

    net probe-in  motion.probe-input <= parport.0.pin-15-in-not
"""

from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.HalFragmentModels import (
    SERVO_THREAD,
    Addf,
    HalFragment,
    PinRequest,
    PinRole,
)

PROBE_SIGNAL = "probe-in"
TOOL_LENGTH_SENSOR_SIGNAL = "tool-length-sensor-in"
OR_NAME = "probe-or"
MOTION_PROBE_INPUT = "motion.probe-input"
MOTION_TYPE_FLOAT = "probe-mtype"
PROBING_WINDOW = "probe-probing"
PROBE_GATE = "probe-gate"
#: ``motion.motion-type`` during G38.x (EMC_MOTION_TYPE_PROBING).
MOTION_TYPE_PROBING = 5


class ProbeHalMapper:
    """Wires the probe and the tool-length sensor into `motion.probe-input`."""

    @staticmethod
    def to_fragment(
        probe: dict[str, Any] | None,
        tool_length_sensor: dict[str, Any] | None = None,
        z_home_joints: list[int] | None = None,
    ) -> HalFragment:
        """``z_home_joints`` (``probe:z_virtual_endstop``): the touch probe
        is also the home switch of these joints — wired ungated::

            net probe-in => joint.2.home-sw-in joint.3.home-sw-in ...
        """
        fragment = HalFragment()
        probe_pin = (probe or {}).get("pin")
        sensor_pin = (tool_length_sensor or {}).get("pin")
        if probe_pin:
            fragment.requests.append(
                PinRequest(signal=PROBE_SIGNAL, role=PinRole.DIGITAL_IN,
                           pin=PinStringMapper.from_string(probe_pin), owner="probe")
            )
        if sensor_pin:
            fragment.requests.append(
                PinRequest(signal=TOOL_LENGTH_SENSOR_SIGNAL, role=PinRole.DIGITAL_IN,
                           pin=PinStringMapper.from_string(sensor_pin), owner="tool_length_sensor")
            )
        if not probe_pin:
            if sensor_pin:
                fragment.nets.append(f"net {TOOL_LENGTH_SENSOR_SIGNAL} => {MOTION_PROBE_INPUT}")
            return fragment

        if z_home_joints:
            fragment.nets.append(
                f"net {PROBE_SIGNAL} => " + " ".join(f"joint.{j}.home-sw-in" for j in z_home_joints)
            )
        probe_out = ProbeHalMapper._gate_to_probing_moves(fragment)
        if not sensor_pin:
            fragment.nets.append(f"net {probe_out} {PROBE_GATE}.out => {MOTION_PROBE_INPUT}")
            return fragment

        # Both switches: either one trips the probe input. The OR runs
        # with the input stage (order 0) — before motion reads it.
        fragment.loadrt.append(f"loadrt or2 names={OR_NAME}")
        fragment.addf.append(Addf(OR_NAME, SERVO_THREAD, order=0))
        fragment.nets.append(f"net {probe_out} {PROBE_GATE}.out => {OR_NAME}.in0")
        fragment.nets.append(f"net {TOOL_LENGTH_SENSOR_SIGNAL} => {OR_NAME}.in1")
        fragment.nets.append(f"net probe-or-out {OR_NAME}.out => {MOTION_PROBE_INPUT}")
        return fragment

    @staticmethod
    def _gate_to_probing_moves(fragment: HalFragment) -> str:
        """Passes ``probe-in`` only while ``motion.motion-type`` is
        :data:`MOTION_TYPE_PROBING` (see the module docstring); returns the
        name of the gated signal."""
        fragment.loadrt.append(f"loadrt conv_s32_float names={MOTION_TYPE_FLOAT}")
        fragment.loadrt.append(f"loadrt wcomp names={PROBING_WINDOW}")
        fragment.loadrt.append(f"loadrt and2 names={PROBE_GATE}")
        # In data-flow order, with the input stage (order 0).
        for name in (MOTION_TYPE_FLOAT, PROBING_WINDOW, PROBE_GATE):
            fragment.addf.append(Addf(name, SERVO_THREAD, order=0))
        fragment.setp.append(f"setp {PROBING_WINDOW}.min {MOTION_TYPE_PROBING - 0.5}")
        fragment.setp.append(f"setp {PROBING_WINDOW}.max {MOTION_TYPE_PROBING + 0.5}")
        fragment.nets.append(f"net probe-motion-type motion.motion-type => {MOTION_TYPE_FLOAT}.in")
        fragment.nets.append(f"net probe-motion-type-f {MOTION_TYPE_FLOAT}.out => {PROBING_WINDOW}.in")
        fragment.nets.append(f"net probe-allowed {PROBING_WINDOW}.out => {PROBE_GATE}.in1")
        fragment.nets.append(f"net {PROBE_SIGNAL} => {PROBE_GATE}.in0")
        return "probe-gated"


__all__ = ["ProbeHalMapper"]
