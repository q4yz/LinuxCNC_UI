"""HalAssembler + `[duplicate_pin_override]` — the case the shared-endstop
trick doesn't cover on its own.

`StepperHalMapper` already makes two axes referencing the *same*
endstop entity collapse onto one signal (`test_hal_assembler.py`'s
`test_a_shared_endstop_produces_exactly_one_physical_route`). This
file covers the other case: two *different* endstop entities that
happen to target the same physical pin — the validator only lets that
through when the operator declared it in
`duplicate_pin_overrides`, and the assembler still has to turn it into
HAL a real machine can load (one physical pin can only ever belong to
one signal).
"""

from __future__ import annotations

from typing import Any

from services.halcompiler.assembler import HalAssembler


def _machine(**overrides: Any) -> dict[str, Any]:
    base = {
        "mcus": [{"id": "mcu", "connection": "parallelport", "interface": "0"}],
        "axes": [
            {"id": "x", "joint_numbers": [0], "endstop": "endstop_x"},
            {"id": "z", "joint_numbers": [3], "endstop": "endstop_z"},
        ],
        "joints": [
            {"id": "stepper_x", "joint_number": 0, "step_pin": "mcu:08", "dir_pin": "mcu:!09"},
            {"id": "stepper_z", "joint_number": 3, "step_pin": "mcu:06", "dir_pin": "mcu:07"},
        ],
        # Two DIFFERENT endstop entities, same physical pin — the case
        # the endstop-id-sharing trick can't collapse on its own.
        "endstops": [
            {"id": "endstop_x", "pin": "mcu:13"},
            {"id": "endstop_z", "pin": "mcu:13"},
        ],
        "duplicate_pin_overrides": ["mcu:13"],
    }
    base.update(overrides)
    return base


def test_two_different_endstops_sharing_a_pin_route_to_one_physical_pin():
    fragment = HalAssembler(_machine()).assemble()
    writer_lines = [n for n in fragment.nets if "pin-13-in" in n]
    assert len(writer_lines) == 1, writer_lines


def test_both_axes_still_read_the_merged_signal():
    fragment = HalAssembler(_machine()).assemble()
    writer_lines = [n for n in fragment.nets if "pin-13-in" in n]
    canonical = writer_lines[0].split()[1]  # "net <signal> <= parport.0.pin-13-in"
    assert f"net {canonical} => joint.0.home-sw-in" in fragment.nets
    assert f"net {canonical} => joint.3.home-sw-in" in fragment.nets
    # The losing signal name must not survive anywhere in the output.
    losing = "endstop_z-sw" if canonical == "endstop_x-sw" else "endstop_x-sw"
    assert not any(losing in n for n in fragment.nets)


def test_without_the_override_pin_the_merge_never_runs():
    """No `duplicate_pin_overrides` declared at all — nothing to merge."""
    fragment = HalAssembler(_machine(duplicate_pin_overrides=[])).assemble()
    writer_lines = [n for n in fragment.nets if "pin-13-in" in n]
    # Both signals still route independently — this machine would fail
    # validation in practice (E_PIN_CONFLICT), but the assembler itself
    # trusts its input and must not silently merge without permission.
    assert len(writer_lines) == 2


def test_merge_is_a_no_op_when_the_signal_names_already_match():
    """A true shared-endstop pair (one entity, two axes) has nothing to merge."""
    machine = _machine(
        axes=[
            {"id": "x", "joint_numbers": [0], "endstop": "endstop_xz"},
            {"id": "z", "joint_numbers": [3], "endstop": "endstop_xz"},
        ],
        endstops=[{"id": "endstop_xz", "pin": "mcu:13"}],
        duplicate_pin_overrides=["mcu:13"],
    )
    fragment = HalAssembler(machine).assemble()
    writer_lines = [n for n in fragment.nets if "pin-13-in" in n]
    assert len(writer_lines) == 1
    assert "net endstop_xz-sw => joint.0.home-sw-in" in fragment.nets
    assert "net endstop_xz-sw => joint.3.home-sw-in" in fragment.nets
