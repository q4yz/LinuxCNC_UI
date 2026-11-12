"""ProbeHalMapper — `.agent/component/probe.md` § 3.

Grounded in the real reference machine,
`machine_config/example/PrintNC-WEBGUI/Machine.hal` (line 93):

    net probe-in  motion.probe-input <= parport.0.pin-15-in-not

Unlike `[estop]`, no MCU-class gating exists here at all —
`motion.probe-input` is a core LinuxCNC motion pin, never a
`loadrt`-owned one, so it never collides with anything a class-B/C
router already claims for its own link-health chain.
"""

from __future__ import annotations

from models.machineconfig.HalFragmentModels import PinRole
from services.halcompiler.components.ProbeHalMapper import ProbeHalMapper


def test_no_probe_at_all_means_an_entirely_empty_fragment():
    """The absent-[probe] case — the normal, common machine."""
    fragment = ProbeHalMapper.to_fragment(None)
    assert fragment.loadrt == []
    assert fragment.nets == []
    assert fragment.requests == []


def test_empty_probe_block_means_an_entirely_empty_fragment():
    """A declared but bare [probe] (pin unset) contributes nothing —
    same as no section at all."""
    fragment = ProbeHalMapper.to_fragment({"pin": None})
    assert fragment.nets == []
    assert fragment.requests == []


def test_declared_pin_reaches_motion_probe_input_only_while_probing():
    """LinuxCNC aborts any non-probe move during which motion.probe-input
    switches on — an inductive probe does at first-layer height. So the
    probe passes only while motion.motion-type is 5 (probing, G38.x)."""
    fragment = ProbeHalMapper.to_fragment({"pin": "!par0:15"})

    assert fragment.loadrt == [
        "loadrt conv_s32_float names=probe-mtype",
        "loadrt wcomp names=probe-probing",
        "loadrt and2 names=probe-gate",
    ]
    assert [a.func for a in fragment.addf] == ["probe-mtype", "probe-probing", "probe-gate"]
    assert fragment.setp == ["setp probe-probing.min 4.5", "setp probe-probing.max 5.5"]
    assert fragment.nets == [
        "net probe-motion-type motion.motion-type => probe-mtype.in",
        "net probe-motion-type-f probe-mtype.out => probe-probing.in",
        "net probe-allowed probe-probing.out => probe-gate.in1",
        "net probe-in => probe-gate.in0",
        "net probe-gated probe-gate.out => motion.probe-input",
    ]
    assert "net probe-in => motion.probe-input" not in fragment.nets

    [request] = fragment.requests
    assert request.signal == "probe-in"
    assert request.role is PinRole.DIGITAL_IN
    assert request.pin.pin_id == "15"
    assert request.pin.invert is True
    assert request.owner == "probe"


__all__ = []
