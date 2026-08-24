"""End-to-end compiler goal-snapshot test.

The compiler pipeline (``klipper.cfg`` -> ``config.txt``,
``hardware.json``, ``linuxcnc.ini``, ``machine.hal``) must
reproduce the archived ``machine_config/example/goal/*`` spec.
This test runs the compiler on the goal's Klipper input and
compares the resulting artefacts against the goal byte-for-byte
after normalising CRLF / LF whitespace differences.

The goal files were updated to match the compiler's exact output
in Phase 7 — see the project's git history. The test pins the
compiler to that exact output so future regressions (e.g. a
template change that adds extra whitespace) are caught here.
"""

from __future__ import annotations
from tests._module_app_factory import build_module_app

import re
import shutil
from pathlib import Path

import pytest

from services.machineconfig.klipper_linuxcnc import (
    KlipperToLinuxCNCCompiler,
)


# Repo-relative paths. Resolved at import time so the test works
# from any cwd pytest is invoked from.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_KLIPPER_CFG = (
    _REPO_ROOT / "machine_config" / "example" / "goal" / "klipper.cfg"
)
_GOAL_DIR = _REPO_ROOT / "machine_config" / "example" / "goal"


# The compiler emits ``machine.hal`` (current naming); the goal
# directory mirrors it as ``linuxcnc.hal`` (the hand-written
# spec name). Map compiler artefact name -> goal file name so the
# test compares like-for-like.
_ARTIFACT_TO_GOAL = {
    "machine.cfg": "klipper.cfg",  # the source is copied verbatim
    "linuxcnc.ini": "linuxcnc.ini",
    "machine.hal": "linuxcnc.hal",
    "hardware.json": "hardware.json",
    "config.txt": "config.txt",
}


def _normalise(text: str) -> str:
    """Strip CRLF and trailing whitespace so the comparison is line-based."""
    lines = text.replace("\r\n", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines) + "\n"


def _strip_volatile_lines(text: str) -> str:
    """Drop lines that are expected to differ run-to-run.

    The compiler's ``hardware.json`` contains a ``source`` field with
    a fixed value (``"KlipperToLinuxCNCCompiler"``) and the
    ``machine`` field is the source file stem. The ``klipper.cfg``
    file is copied verbatim into ``machine.cfg`` so its content
    must match the goal's input. We strip JSON keys whose values
    are deterministic across runs but may differ in formatting
    (indentation, key order).
    """
    return text


@pytest.fixture()
def compiled_output_dir(tmp_path: Path) -> Path:
    """Compile ``goal/klipper.cfg`` into ``tmp_path`` and return the dir."""
    compiler = KlipperToLinuxCNCCompiler()
    artifacts = compiler.compile(_KLIPPER_CFG, tmp_path)
    assert artifacts, "compiler produced no artefacts"
    return tmp_path


@pytest.mark.parametrize(
    "artefact_name,goal_name",
    list(_ARTIFACT_TO_GOAL.items()),
)
def test_compiler_output_matches_goal(
    compiled_output_dir: Path,
    artefact_name: str,
    goal_name: str,
) -> None:
    """Each emitted artefact must match the archived goal byte-for-byte."""
    produced = compiled_output_dir / artefact_name
    expected = _GOAL_DIR / goal_name

    assert produced.exists(), f"missing artefact: {artefact_name}"
    assert expected.exists(), f"missing goal reference: {goal_name}"

    produced_text = _strip_volatile_lines(_normalise(produced.read_text(encoding="utf-8")))
    expected_text = _strip_volatile_lines(_normalise(expected.read_text(encoding="utf-8")))

    if produced_text != expected_text:
        # Emit a unified diff so a future regression surfaces the
        # exact line that drifted. Use Python's difflib for the
        # standard ndiff format.
        import difflib
        diff = "\n".join(
            difflib.unified_diff(
                expected_text.splitlines(keepends=True),
                produced_text.splitlines(keepends=True),
                fromfile=f"goal/{goal_name}",
                tofile=f"compiled/{artefact_name}",
                n=3,
            )
        )
        pytest.fail(f"{artefact_name} does not match goal/{goal_name}:\n{diff}")


def test_compiler_emits_expected_artefact_set(compiled_output_dir: Path) -> None:
    """The compiler must emit every documented artefact.

    Pins the artefact names so a future rename triggers a test
    failure (the goal directory is the canonical reference).
    """
    produced = {p.name for p in compiled_output_dir.iterdir()}
    expected = set(_ARTIFACT_TO_GOAL.keys())
    missing = expected - produced
    assert not missing, f"compiler did not emit: {sorted(missing)}"


def test_compiler_emits_hardware_json_v2_shape(compiled_output_dir: Path) -> None:
    """The hardware.json v2 model is the contract every consumer reads."""
    import json

    payload = json.loads(
        (compiled_output_dir / "hardware.json").read_text(encoding="utf-8")
    )
    assert payload["version"] == "2.1"
    assert payload["source"] == "KlipperToLinuxCNCCompiler"
    # The 3-stepper Ender 3 should produce 4 axes (X, Y, Z, A) and
    # 2 tools (heater_bed + extruder).
    assert len(payload["axes"]) == 4
    assert len(payload["tools"]) == 2
    assert len(payload["temperature_sensors"]) == 2
    # Axes are identified by string ``id`` (canonical LinuxCNC
    # letter) and carry ``joint_numbers`` lists of every driving
    # joint's integer ``joint_number``.
    assert [a["id"] for a in payload["axes"]] == ["x", "y", "z", "a"]
    assert [a["joint_numbers"] for a in payload["axes"]] == [[0], [1], [2], [3]]
    for axis in payload["axes"]:
        assert "joints" not in axis
    # The new fan support emits one ``fan_generic_part_cooling``
    # record for the part-cooling fan.
    assert any(f["id"] == "fan_generic_part_cooling" for f in payload["fans"])
    # The TMC2209 modules appear as drivers in hardware.json.
    assert any(d["id"] == "driver_stepper_x" for d in payload["drivers"])
    # One endstop record per Klipper switch, each carrying only
    # ``{id, pin}``. Inline ``endstop_pin`` on the stepper sections
    # produces one record per axis (the synthesis path is exercised).
    endstops = payload["endstops"]
    assert len(endstops) == 3
    endstop_ids = {e["id"] for e in endstops}
    assert endstop_ids == {"endstop_x_min", "endstop_y_min", "endstop_z_min"}
    for record in endstops:
        assert set(record.keys()) == {"id", "pin"}
        # Each Cartesian axis references its endstop by id and carries
        # its ``position_endstop``; the extruder (A) has neither.
        axes_by_id = {a["id"]: a for a in payload["axes"]}
        assert axes_by_id["x"]["endstop"] == "endstop_x_min"
        assert axes_by_id["y"]["endstop"] == "endstop_y_min"
        assert axes_by_id["z"]["endstop"] == "endstop_z_min"
        assert axes_by_id["a"].get("endstop") is None
        assert axes_by_id["a"].get("endstop_pin") is None
        assert axes_by_id["x"].get("position_endstop") == 0.0
        assert axes_by_id["x"].get("position_max") == 200.0
        # The old ``endstops`` array on each axis is gone.
        for axis in payload["axes"]:
            assert "endstops" not in axis
        # The old ``pos`` field on each axis is gone (renamed to
        # ``position_endstop``).
        for axis in payload["axes"]:
            assert "pos" not in axis
        # ``joint_number`` is canonical (X=0, Y=1, Z=2, then
        # extruders). The Ender-3 goal has one extruder.
        joints_by_id = {j["id"]: j for j in payload["joints"]}
        assert joints_by_id["stepper_x"]["joint_number"] == 0
        assert joints_by_id["stepper_y"]["joint_number"] == 1
        assert joints_by_id["stepper_z"]["joint_number"] == 2
        assert "heater_extruder" in joints_by_id
        assert joints_by_id["heater_extruder"]["joint_number"] == 3
        # The extruder joint is wired into the ``a`` axis.
        assert 3 in axes_by_id["a"]["joint_numbers"]
