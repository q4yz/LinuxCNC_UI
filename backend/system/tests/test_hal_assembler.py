"""HalAssembler — the two-pass join, ordering, and de-duplication.

Per-mapper content is covered by each mapper's own test file; this
file is about what only the assembler can get wrong: routing requests
to the right MCU, collapsing a shared signal to one physical route,
and refusing rather than guessing when no router exists yet.
"""

from __future__ import annotations

import pytest

from typing import Any

from services.halcompiler.assembler import HalAssembler, UnsupportedMcuError


def _machine(**overrides: Any) -> dict[str, Any]:
    base = {
        "mcus": [{"id": "mcu", "connection": "parallelport", "interface": "0"}],
        "axes": [{"id": "x", "joint_numbers": [0], "endstop": "endstop_xz"},
                 {"id": "z", "joint_numbers": [3], "endstop": "endstop_xz"}],
        "joints": [
            {"id": "stepper_x", "joint_number": 0, "step_pin": "mcu:08", "dir_pin": "mcu:!09"},
            {"id": "stepper_z", "joint_number": 3, "step_pin": "mcu:06", "dir_pin": "mcu:07"},
        ],
        "endstops": [{"id": "endstop_xz", "pin": "mcu:!13"}],
    }
    base.update(overrides)
    return base


def test_a_shared_endstop_produces_exactly_one_physical_route():
    fragment = HalAssembler(_machine()).assemble()
    writer_lines = [n for n in fragment.nets if "pin-13-in-not" in n]
    assert writer_lines == ["net endstop_xz-sw <= parport.0.pin-13-in-not"]
    # Both joints still get wired to the one shared signal.
    assert "net endstop_xz-sw => joint.0.home-sw-in" in fragment.nets
    assert "net endstop_xz-sw => joint.3.home-sw-in" in fragment.nets


def test_capability_class_ignores_an_unrelated_io_only_mcu():
    """A VFD spindle MCU declared first must not make the machine class C."""
    machine = _machine(
        mcus=[
            {"id": "vfd0", "connection": "vfd_rs485"},
            {"id": "mcu", "connection": "parallelport", "interface": "0"},
        ]
    )
    fragment = HalAssembler(machine).assemble()
    # Class A signature: stepgen loaded, sized to the joint count.
    assert any(line.startswith("loadrt stepgen") for line in fragment.loadrt)


def test_unrouted_mcu_type_raises_rather_than_silently_dropping_pins():
    """``remora-eth`` has no reference machine yet — still honestly unrouted."""
    machine = _machine(
        mcus=[{"id": "mcu", "connection": "remora-eth"}],
    )
    with pytest.raises(UnsupportedMcuError, match="remora-eth"):
        HalAssembler(machine).assemble()


def test_a_request_targeting_an_undeclared_mcu_does_not_crash():
    """E_UNKNOWN_MCU is the validator's job — the assembler must not raise on it."""
    machine = _machine()
    machine["joints"][0]["step_pin"] = "ghost:08"
    fragment = HalAssembler(machine).assemble()
    assert not any("ghost" in n for n in fragment.nets)


def test_component_nets_precede_router_nets():
    """README § 4: router output is always last, since it consumes what
    every other component exported."""
    fragment = HalAssembler(_machine()).assemble()
    component_idx = fragment.nets.index("net xpos-cmd joint.0.motor-pos-cmd => stepgen.0.position-cmd")
    router_idx = fragment.nets.index("net stepper_x-step => parport.0.pin-08-out")
    assert component_idx < router_idx


def test_router_base_setp_and_stepgen_setp_both_present():
    fragment = HalAssembler(_machine()).assemble()
    assert "setp parport.0.reset-time 2500" in fragment.setp
    assert "setp stepgen.0.position-scale [JOINT_0]SCALE" in fragment.setp


def test_a_bare_class_b_machine_still_loads_its_own_mcu():
    """A minimal Remora machine — one joint, no endstops, no heaters,
    nothing else that would ever generate a routed `PinRequest` —
    must still `loadrt remora-spi`. The board owns `remora.joint.0.*`,
    which every joint net already references; skipping the board's own
    load just because nothing *else* routes through it would produce
    HAL that references pins nothing ever created.
    """
    machine = {
        "mcus": [{"id": "mcu", "connection": "remora-spi"}],
        "axes": [{"id": "x", "joint_numbers": [0]}],
        "joints": [{"id": "stepper_x", "joint_number": 0, "step_pin": "mcu:PF13"}],
        "endstops": [],
    }
    fragment = HalAssembler(machine).assemble()
    assert any(line.startswith("loadrt remora-spi") for line in fragment.loadrt)
    assert any("remora.SPI-enable" in n for n in fragment.nets)
    assert any(a.func == "remora.read" for a in fragment.addf)


def test_tmc2209_driver_produces_a_firmware_module_on_class_b_only():
    """`config.txt` doesn't exist for a class-A machine — a driver's
    UART tuning must not fabricate one for a board that will never
    read it."""
    remora_machine = {
        "mcus": [{"id": "mcu", "connection": "remora-spi"}],
        "axes": [{"id": "x", "joint_numbers": [0]}],
        "joints": [
            {"id": "stepper_x", "joint_number": 0, "step_pin": "mcu:PF13", "driver": "driver_x"}
        ],
        "drivers": [{"id": "driver_x", "type": "TMC2209", "uart_pin": "mcu:PC6"}],
        "endstops": [],
    }
    fragment = HalAssembler(remora_machine).assemble()
    config = fragment.files["config_mcu.txt"]
    assert '"Type": "TMC2209"' in config

    parport_machine = _machine(
        joints=[
            {
                "id": "stepper_x",
                "joint_number": 0,
                "step_pin": "mcu:08",
                "dir_pin": "mcu:!09",
                "driver": "driver_x",
            },
            {"id": "stepper_z", "joint_number": 3, "step_pin": "mcu:06", "dir_pin": "mcu:07"},
        ],
        drivers=[{"id": "driver_x", "type": "TMC2209", "uart_pin": "mcu:PC6"}],
    )
    fragment = HalAssembler(parport_machine).assemble()
    assert not any(k.startswith("config_") for k in fragment.files)
