"""`[probe]` + `[tool_length_sensor]` -> :class:`HalFragment` (`.agent/component/probe.md`).

LinuxCNC has exactly one probe input, `motion.probe-input` (a core
motion pin — no `loadrt`). A machine can have two switches that should
trigger it: the touch probe and the tool-length sensor (tool setter).
Both are owned here because they share that one pin:

* only one declared  -> its signal drives `motion.probe-input` directly;
* both declared      -> an `or2` merges them, so either switch trips:

      loadrt or2 names=probe-or
      addf probe-or servo-thread
      net probe-in              => probe-or.in0
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
Z_HOMING_NOT = "probe-z-homing-not"
PROBE_GATE = "probe-gate"


class ProbeHalMapper:
    """Wires the probe and the tool-length sensor into `motion.probe-input`."""

    @staticmethod
    def to_fragment(
        probe: dict[str, Any] | None,
        tool_length_sensor: dict[str, Any] | None = None,
        z_home_joints: list[int] | None = None,
    ) -> HalFragment:
        """``z_home_joints`` (``probe:z_virtual_endstop``): the touch probe
        is also the home switch of these joints, and ``motion.probe-input``
        only sees it while none of them homes — LinuxCNC aborts a homing
        move during which the probe input trips ("probe tripped during
        non-probe move")::

            net probe-in => joint.2.home-sw-in joint.3.home-sw-in ...
            net probe-z-homing joint.2.homing => probe-z-homing-not.in
            net probe-allowed probe-z-homing-not.out => probe-gate.in1
            net probe-in => probe-gate.in0
            net probe-gated probe-gate.out => motion.probe-input
        """
        if z_home_joints and (probe or {}).get("pin"):
            return ProbeHalMapper._with_z_home(probe or {}, tool_length_sensor, list(z_home_joints))
        fragment = HalFragment()
        inputs = [
            (signal, owner, pin)
            for signal, owner, record in (
                (PROBE_SIGNAL, "probe", probe),
                (TOOL_LENGTH_SENSOR_SIGNAL, "tool_length_sensor", tool_length_sensor),
            )
            if (pin := (record or {}).get("pin"))
        ]
        if not inputs:
            return fragment

        for signal, owner, pin in inputs:
            fragment.requests.append(
                PinRequest(
                    signal=signal,
                    role=PinRole.DIGITAL_IN,
                    pin=PinStringMapper.from_string(pin),
                    owner=owner,
                )
            )

        if len(inputs) == 1:
            signal = inputs[0][0]
            fragment.nets.append(f"net {signal} => {MOTION_PROBE_INPUT}")
            return fragment

        # Both switches: either one trips the probe input. The OR runs
        # with the input stage (order 0) — before motion reads it.
        fragment.loadrt.append(f"loadrt or2 names={OR_NAME}")
        fragment.addf.append(Addf(OR_NAME, SERVO_THREAD, order=0))
        for index, (signal, _owner, _pin) in enumerate(inputs):
            fragment.nets.append(f"net {signal} => {OR_NAME}.in{index}")
        fragment.nets.append(f"net probe-or-out {OR_NAME}.out => {MOTION_PROBE_INPUT}")
        return fragment

    @staticmethod
    def _with_z_home(
        probe: dict[str, Any],
        tool_length_sensor: dict[str, Any] | None,
        z_home_joints: list[int],
    ) -> HalFragment:
        """The probe as the Z home switch, gated off ``motion.probe-input``
        while Z homes (see :meth:`to_fragment`). A tool-length sensor still
        ORs in after the gate — it is no home switch."""
        fragment = HalFragment()
        fragment.requests.append(
            PinRequest(signal=PROBE_SIGNAL, role=PinRole.DIGITAL_IN,
                       pin=PinStringMapper.from_string(probe["pin"]), owner="probe")
        )
        fragment.nets.append(
            f"net {PROBE_SIGNAL} => " + " ".join(f"joint.{j}.home-sw-in" for j in z_home_joints)
        )
        # All Z joints home together (one HOME_SEQUENCE): the first one's homing pin is Z's.
        fragment.loadrt.append(f"loadrt not names={Z_HOMING_NOT}")
        fragment.loadrt.append(f"loadrt and2 names={PROBE_GATE}")
        fragment.addf.append(Addf(Z_HOMING_NOT, SERVO_THREAD, order=0))
        fragment.addf.append(Addf(PROBE_GATE, SERVO_THREAD, order=0))
        fragment.nets.append(f"net probe-z-homing joint.{z_home_joints[0]}.homing => {Z_HOMING_NOT}.in")
        fragment.nets.append(f"net probe-allowed {Z_HOMING_NOT}.out => {PROBE_GATE}.in1")
        fragment.nets.append(f"net {PROBE_SIGNAL} => {PROBE_GATE}.in0")

        if tool_length_sensor is None or not tool_length_sensor.get("pin"):
            fragment.nets.append(f"net probe-gated {PROBE_GATE}.out => {MOTION_PROBE_INPUT}")
            return fragment

        fragment.requests.append(
            PinRequest(signal=TOOL_LENGTH_SENSOR_SIGNAL, role=PinRole.DIGITAL_IN,
                       pin=PinStringMapper.from_string(tool_length_sensor["pin"]), owner="tool_length_sensor")
        )
        fragment.loadrt.append(f"loadrt or2 names={OR_NAME}")
        fragment.addf.append(Addf(OR_NAME, SERVO_THREAD, order=0))
        fragment.nets.append(f"net probe-gated {PROBE_GATE}.out => {OR_NAME}.in0")
        fragment.nets.append(f"net {TOOL_LENGTH_SENSOR_SIGNAL} => {OR_NAME}.in1")
        fragment.nets.append(f"net probe-or-out {OR_NAME}.out => {MOTION_PROBE_INPUT}")
        return fragment


__all__ = ["ProbeHalMapper"]
