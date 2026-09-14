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

from models.machineconfig.hal_fragment_models import PinRole
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


def test_declared_pin_wires_motion_probe_input():
    fragment = ProbeHalMapper.to_fragment({"pin": "!par0:15"})

    assert "net probe-in => motion.probe-input" in fragment.nets
    assert fragment.loadrt == []  # motion.probe-input needs no loadrt

    [request] = fragment.requests
    assert request.signal == "probe-in"
    assert request.role is PinRole.DIGITAL_IN
    assert request.pin.pin_id == "15"
    assert request.pin.invert is True
    assert request.owner == "probe"


__all__ = []
