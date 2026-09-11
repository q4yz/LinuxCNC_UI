"""``hardware.json`` must not lose information from the source ``.cfg``.

The decision (2026-09-09): hardware.json is the compilation-complete
IR, so it may carry fields the UI never reads. The corollary is that
*nothing* the parser understood may be dropped on the way out — a HAL
compiler reading only this file has to be able to reproduce the
machine.

Three distinct leaks were possible before this test existed, and all
three had live examples:

1. **Keyword rejected** — ``full_steps_per_rotation`` was not in
   ``STEPPER_KEYS``, so ``printnc.cfg`` failed to parse at all.
2. **Parsed then discarded** — ``STEPPER_KEYS`` allowed
   ``position_min`` / ``homing_speed`` but ``_parse_stepper`` never
   read them into the :class:`Stepper` dataclass.
3. **On the entity, never emitted** — PID gains, ``[printer]`` motion
   limits and every TMC driver setting reached the graph and stopped
   there.

The check walks the parsed graph's dataclass fields and asserts each
populated value reaches the emitted payload. ``ALLOWED_DROPS`` is the
escape hatch: a field listed there is deliberately not emitted, with
the reason recorded. Adding a parser field without either emitting it
or listing it here fails this test.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from machineconfig_parser import MachineConfigParser
from services.machineconfig.hardware_json_generator import build_hardware_json

REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILE_DIR = REPO_ROOT / "machine_config" / "profiles"

#: ``entity attribute -> why it is intentionally not in hardware.json``.
#: Keep this list short and justified; it is the only sanctioned way to
#: drop something the operator wrote.
ALLOWED_DROPS: dict[str, str] = {
    # Structural back-references, not user data — the emitted payload
    # expresses the same relationship as an id string.
    "stepper": "link back to the owning stepper; emitted as a joint/driver id",
    "endstops": "linked EndstopSwitch objects; emitted as the endstops[] list",
    "heater": "an Extruder's embedded Heater; emitted as one tools[] entry",
    "axis": "the axis letter; emitted as axes[].id and the joint id",
    "name": "entity key; emitted as the record's id",
    "kinematics": "emitted at the payload root",
}


def _profiles() -> list[Path]:
    return sorted(PROFILE_DIR.glob("*.cfg"))


def _scalars(payload) -> set[str]:
    """Every scalar value present anywhere in the emitted payload."""
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif node is not None:
            found.add(str(node))

    walk(payload)
    return found


def _entities(graph) -> dict[str, list[object]]:
    return {
        "printer": [graph.printer] if graph.printer else [],
        "estop": [graph.estop] if graph.estop else [],
        "stepper": list(graph.steppers.values()),
        "endstop_switch": list(graph.endstop_switches.values()),
        "heater": list(graph.heaters.values()),
        "spindle_analog": [graph.spindle_analog] if graph.spindle_analog else [],
        "spindle_digital": list(graph.spindle_digitals.values()),
        "tmc2209": list(graph.tmc2209s.values()),
        "fan": list(graph.fans.values()),
        "heater_fan": list(graph.heater_fans.values()),
        "mcu": list(graph.mcus.values()),
    }


@pytest.mark.parametrize("profile", _profiles(), ids=lambda p: p.name)
def test_every_parsed_field_reaches_hardware_json(profile: Path) -> None:
    graph = MachineConfigParser().parse(profile)
    payload = build_hardware_json(graph, profile.stem)
    present = _scalars(payload)

    dropped: list[str] = []
    for entity_name, items in _entities(graph).items():
        for item in items:
            if not dataclasses.is_dataclass(item):
                continue
            for field in dataclasses.fields(item):
                if field.name in ALLOWED_DROPS:
                    continue
                value = getattr(item, field.name, None)
                if value is None or value in ("", [], {}):
                    continue
                if dataclasses.is_dataclass(value):
                    continue
                if str(value) in present:
                    continue
                dropped.append(f"{entity_name}.{field.name} = {value!r}")

    assert not dropped, (
        f"{profile.name}: parsed but never emitted into hardware.json:\n  "
        + "\n  ".join(sorted(set(dropped)))
        + "\n\nEmit the field, or add it to ALLOWED_DROPS with a reason."
    )


@pytest.mark.parametrize("profile", _profiles(), ids=lambda p: p.name)
def test_every_profile_still_parses(profile: Path) -> None:
    """A shipped profile that no longer parses is a schema regression.

    ``printnc.cfg`` used to fail here: it declares
    ``full_steps_per_rotation``, which ``STEPPER_KEYS`` did not allow.
    """
    graph = MachineConfigParser().parse(profile)
    assert graph is not None


def test_compiler_relevant_fields_are_emitted() -> None:
    """Spot-check the fields the HAL compiler specifically needs.

    The generic walk above proves nothing was *dropped*; this proves
    the compiler-facing ones land under the names the component
    templates in ``.agent/component/`` expect.
    """
    graph = MachineConfigParser().parse(PROFILE_DIR / "klipper.cfg")
    payload = json.loads(json.dumps(build_hardware_json(graph, "test")))

    assert payload["version"] == "2.2"
    # [printer] motion envelope -> [TRAJ] limits
    assert payload["max_velocity"] is not None
    assert payload["max_accel"] is not None

    # PID gains -> the heater loop's INI section (heater.md § 3)
    heaters = [t for t in payload["tools"] if t["type"] in ("extruder", "heated_bed")]
    assert heaters, "profile should declare at least one heater"
    assert any(h.get("pid_kp") is not None for h in heaters)

    # Driver settings are no longer hardcoded None
    assert any(d.get("run_current") is not None for d in payload["drivers"])
    assert any(d.get("uart_pin") is not None for d in payload["drivers"])
