"""End-to-end compile, checked against a real, working class-B machine.

`machine_config/example/ender3/ender3.hal` + `3Dprinter.hal` are a
hand-written, functional Remora SPI (class B) config — a real Ender 3
running an SKR v1.4 board via Remora. This fixture mirrors its joint
layout (read directly off those files) as `hardware.json`, compiles
it, and checks the output is *structurally* equivalent — same
components loaded, same `addf` order, same net-graph shape — not a
byte-for-byte diff.

The one deliberate structural difference from the reference text: the
real file writes one combined `net X-stop remora.input.00 =>
joint.0.home-sw-in joint.0.neg-lim-sw-in` line. This compiler instead
splits writer and reader across two `net <signal> ...` statements —
the same split Phase 1 already uses for parport endstops (the
component mapper emits the reader, the router emits the writer). HAL
lets a net name accumulate targets across statements, so the result is
functionally identical; only the split is new relative to the source
text, not the wiring itself.

Facts asserted here are quoted from those files, not invented:

  * 4 joints: X(0), Y(1), Z(2), extruder/A(3) — `ender3.hal` "joint N setup"
  * no joint has `steplen`/`stepspace`/`dirhold`/`dirsetup` — Remora owns pulses
  * `remora.joint.N.enable` is wired for every joint, unconditionally
  * addf order: `remora.read` -> motion-command-handler ->
    motion-controller -> `remora.update-freq` -> `remora.write`,
    all servo-thread, no base-thread functions at all
  * `3Dprinter.hal`: only X/Y/Z (joints 0-2) have an endstop; the
    extruder (joint 3) has none
  * each wired endstop targets both `home-sw-in` and `neg-lim-sw-in`
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from services.halcompiler import compile_machine_hal, validate_machine
from services.halcompiler.assembler import HalAssembler

REPO_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_HAL = REPO_ROOT / "machine_config" / "example" / "ender3" / "ender3.hal"
REFERENCE_ENDSTOPS = REPO_ROOT / "machine_config" / "example" / "ender3" / "3Dprinter.hal"

PAYLOAD: dict[str, Any] = {
    "version": "2.2",
    "machine": "ender3_reference",
    "source": "test",
    "kinematics": "cartesian",
    "hal_type": "remora",
    "mcus": [{"id": "mcu", "connection": "remora-spi", "parameters": {"spi_clk_div": 64}}],
    "axes": [
        {"id": "x", "joint_numbers": [0], "endstop": "endstop_x"},
        {"id": "y", "joint_numbers": [1], "endstop": "endstop_y"},
        {"id": "z", "joint_numbers": [2], "endstop": "endstop_z"},
        {"id": "a", "joint_numbers": [3]},
    ],
    "joints": [
        {"id": "stepper_x", "joint_number": 0, "step_pin": "mcu:PF13", "dir_pin": "mcu:PF12", "enable_pin": "mcu:PF14"},
        {"id": "stepper_y", "joint_number": 1, "step_pin": "mcu:PG0", "dir_pin": "mcu:PG1", "enable_pin": "mcu:PF15"},
        {"id": "stepper_z", "joint_number": 2, "step_pin": "mcu:PF11", "dir_pin": "mcu:PG3", "enable_pin": "mcu:PG5"},
        {"id": "extruder", "joint_number": 3, "step_pin": "mcu:PF9", "dir_pin": "mcu:PF10", "enable_pin": "mcu:PG2"},
    ],
    "drivers": [],
    "fans": [],
    "temperature_sensors": [],
    "tools": [],
    "endstops": [
        {"id": "endstop_x", "pin": "mcu:PC0"},
        {"id": "endstop_y", "pin": "mcu:PC1"},
        {"id": "endstop_z", "pin": "mcu:PC2"},
    ],
}


@pytest.fixture()
def fragment():
    return HalAssembler(PAYLOAD).assemble()


def test_reference_files_exist():
    assert REFERENCE_HAL.exists(), f"reference machine missing: {REFERENCE_HAL}"
    assert REFERENCE_ENDSTOPS.exists(), f"reference machine missing: {REFERENCE_ENDSTOPS}"


def test_fixture_validates_clean():
    assert validate_machine(PAYLOAD) == []


def test_component_set_matches_the_reference_machine():
    fragment = HalAssembler(PAYLOAD).assemble()
    reference = REFERENCE_HAL.read_text(encoding="utf-8")

    for loadrt_component in ("KINEMATICS", "EMCMOT", "remora-spi"):
        assert any(loadrt_component in line for line in fragment.loadrt), loadrt_component
        assert loadrt_component in reference, f"test fixture drifted from {loadrt_component}"

    # Class B: never a stepgen.
    assert not any("stepgen" in line for line in fragment.loadrt)
    assert "stepgen" not in reference


def test_addf_is_all_servo_thread_no_base_thread_at_all():
    fragment = HalAssembler(PAYLOAD).assemble()
    assert not any(a.thread == "base-thread" for a in fragment.addf)

    servo = [a.func for a in sorted(fragment.addf, key=lambda a: a.order)]
    assert servo == [
        "remora.read",
        "motion-command-handler",
        "motion-controller",
        "remora.update-freq",
        "remora.write",
    ]


def test_no_stepgen_timing_setp_for_any_joint(fragment):
    assert not any(
        keyword in s for s in fragment.setp for keyword in ("steplen", "stepspace", "dirhold", "dirsetup")
    )


def test_position_loop_and_enable_present_for_every_joint(fragment):
    for n in range(4):
        assert f"setp remora.joint.{n}.scale [JOINT_{n}]SCALE" in fragment.setp
        assert f"setp remora.joint.{n}.maxaccel [JOINT_{n}]STEPGEN_MAXACCEL" in fragment.setp
        assert f"net j{n}pos-cmd joint.{n}.motor-pos-cmd => remora.joint.{n}.pos-cmd" in fragment.nets
        assert f"net j{n}pos-fb remora.joint.{n}.pos-fb => joint.{n}.motor-pos-fb" in fragment.nets
        assert f"net j{n}enable joint.{n}.amp-enable-out => remora.joint.{n}.enable" in fragment.nets


def test_joint_pins_never_become_hal_nets(fragment):
    for pin in ("PF13", "PF12", "PF14", "PG0", "PG1", "PF15", "PF11", "PG3", "PG5", "PF9", "PF10", "PG2"):
        assert not any(pin in n for n in fragment.nets), pin
        assert not any(pin in s for s in fragment.setp), pin


def test_only_xyz_have_endstops_the_extruder_does_not(fragment):
    """`3Dprinter.hal` wires X/Y/Z only — joint 3 (extruder) has none."""
    for n, endstop_id in ((0, "endstop_x"), (1, "endstop_y"), (2, "endstop_z")):
        assert f"net {endstop_id}-sw => joint.{n}.home-sw-in joint.{n}.neg-lim-sw-in" in fragment.nets
    assert not any("joint.3.home-sw-in" in n for n in fragment.nets)


def test_endstop_writers_are_zero_padded_and_sequential(fragment):
    assert any("remora.input.00" in n for n in fragment.nets)
    assert any("remora.input.01" in n for n in fragment.nets)
    assert any("remora.input.02" in n for n in fragment.nets)


def test_firmware_config_carries_every_joint_and_endstop_module(fragment):
    config_key = next(k for k in fragment.files if k.startswith("config_"))
    assert config_key == "config_mcu.txt"

    import json

    config = json.loads(fragment.files[config_key])
    assert config["Thread"]["Base"]["Frequency"] > 0
    assert config["Thread"]["Servo"]["Frequency"] > 0

    steppers = [m for m in config["Modules"] if m["Type"] == "Stepper"]
    assert len(steppers) == 4
    assert {m["Joint Number"] for m in steppers} == {0, 1, 2, 3}

    digital_pins = [m for m in config["Modules"] if m["Type"] == "DigitalPin"]
    assert len(digital_pins) == 3
    assert {m["Comment"] for m in digital_pins} == {"endstop_x", "endstop_y", "endstop_z"}


def test_full_render_is_well_formed_hal_text():
    text = compile_machine_hal(PAYLOAD)
    assert text.count("loadrt remora-spi") == 1
    lines = [l for l in text.splitlines() if l.strip()]
    assert all(
        l.startswith(("loadrt ", "addf ", "setp ", "net ", "#")) for l in lines
    ), [l for l in lines if not l.startswith(("loadrt ", "addf ", "setp ", "net ", "#"))]
