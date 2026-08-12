"""Tests for the multi-MCU compiler path.

These tests target the compiler-side logic added on top of the
parser:

* :func:`config_txt_generator.resolve_remora_mcu` correctly
  classifies the graph as ``"single"`` / ``"none"`` /
  ``"ambiguous"``.
* The emitter only renders stepgen / driver / endstop / PWM /
  Temperature modules for pins that belong to the single resolved
  remora MCU; pins on other transports are silently dropped.
* The Remora ``Board`` field is sourced from the remora MCU section,
  not the historical hard-coded literal.
* :func:`hardware_json_generator.build_hardware_json` exposes the
  declared MCU list at the top level of ``hardware.json``.
* The HAL generator emits a single-line diagnostic comment when
  the profile declares non-remora transports so an operator knows
  why some pins didn't make it to the remora payload.

All tests use the strict Klipper parser end-to-end via
:func:`modules.machineconfig.parser.parse_config`; the compiler
itself is never called with a hand-rolled graph so the assertions
mirror what the production code path produces.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.machineconfig.compilers.config_txt_generator import (
    REMORA_CONNECTION_TYPES,
    build_config_txt,
    resolve_remora_mcu,
    write_config_txt,
)
from modules.machineconfig.compilers.hal_generator import build_hal_from_graph
from modules.machineconfig.compilers.hardware_json_generator import (
    build_hardware_json,
)
from modules.machineconfig.models import MCU
from modules.machineconfig.parser import parse_config


# --------------------------------------------------------------------- #
# Helpers                                                                #
# --------------------------------------------------------------------- #


def _write_profile(tmp_path: Path, body: str) -> Path:
    cfg = tmp_path / "machine.cfg"
    cfg.write_text(body, encoding="utf-8")
    return cfg


def _stepper_section(
    axis: str,
    *,
    pins: tuple[str, str, str] = ("PF11", "PG3", "!PG5"),
    rotation_distance: float = 40.0,
    microsteps: int = 16,
    endstop: str | None = None,
) -> str:
    endstop_line = f"endstop_pin: {endstop}\n" if endstop else ""
    return (
        f"[stepper_{axis}]\n"
        f"step_pin: {pins[0]}\n"
        f"dir_pin: {pins[1]}\n"
        f"enable_pin: {pins[2]}\n"
        f"rotation_distance: {rotation_distance}\n"
        f"microsteps: {microsteps}\n"
        f"{endstop_line}"
    )


# --------------------------------------------------------------------- #
# resolve_remora_mcu — single / none / ambiguous                         #
# --------------------------------------------------------------------- #


def test_resolve_remora_mcu_single(tmp_path: Path) -> None:
    cfg = _write_profile(
        tmp_path,
        "[mcu]\nconnection: remora-spi\nboard: BIGTREETECH OCTOPUS\n"
        + _stepper_section("x"),
    )
    graph = parse_config(cfg)
    mcu, mode = resolve_remora_mcu(graph)
    assert mode == "single"
    assert mcu is graph.mcus["mcu"]
    assert mcu.connection == "remora-spi"
    assert mcu.board == "BIGTREETECH OCTOPUS"


def test_resolve_remora_mcu_none_when_all_non_remora(tmp_path: Path) -> None:
    """If no MCU declares a remora transport the mode is ``"none"``."""

    cfg = _write_profile(
        tmp_path,
        "[mcu rs485_com]\n"
        "connection: rs485\n"
        "interface: com0\n"
        "[mcu dummy_a]\n"
        "connection: dummy\n"
        + _stepper_section("x"),
    )
    graph = parse_config(cfg)
    mcu, mode = resolve_remora_mcu(graph)
    assert mode == "none"
    assert mcu is None


def test_resolve_remora_mcu_ambiguous_when_two_remoras(tmp_path: Path) -> None:
    """When two remora MCUs are declared the generator refuses to pick one."""

    cfg = _write_profile(
        tmp_path,
        "[mcu a]\n"
        "connection: remora-spi\n"
        "board: BIGTREETECH OCTOPUS\n"
        "[mcu b]\n"
        "connection: remora-eth\n"
        "board: SKR2\n"
        + _stepper_section("x"),
    )
    graph = parse_config(cfg)
    mcu, mode = resolve_remora_mcu(graph)
    assert mode == "ambiguous"
    assert mcu is None


# --------------------------------------------------------------------- #
# config.txt — Board field, pin routing, file deletion rules            #
# --------------------------------------------------------------------- #


def test_config_txt_board_read_from_remora_mcu(tmp_path: Path) -> None:
    cfg = _write_profile(
        tmp_path,
        "[mcu]\nconnection: remora-spi\nboard: SKR2\n"
        + _stepper_section("x"),
    )
    graph = parse_config(cfg)
    payload = build_config_txt(graph, "test")
    assert payload["Board"] == "SKR2"


def test_config_txt_skipped_when_no_remora_mcu(tmp_path: Path) -> None:
    """Zero remora MCUs → config.txt modules list is empty."""

    cfg = _write_profile(
        tmp_path,
        "[mcu rs485]\nconnection: rs485\ninterface: com0\n"
        + _stepper_section("x"),
    )
    graph = parse_config(cfg)
    payload = build_config_txt(graph, "test")
    assert payload == {"Board": "", "Modules": []}


def test_config_txt_skipped_when_two_remoras(tmp_path: Path) -> None:
    """Ambiguous remora ownership → config.txt modules list is empty."""

    cfg = _write_profile(
        tmp_path,
        "[mcu a]\nconnection: remora-spi\nboard: BIGTREETECH OCTOPUS\n"
        "[mcu b]\nconnection: remora-eth\nboard: SKR2\n"
        + _stepper_section("x"),
    )
    graph = parse_config(cfg)
    payload = build_config_txt(graph, "test")
    assert payload == {"Board": "", "Modules": []}


def test_write_config_txt_deletes_stale_file_when_skipped(tmp_path: Path) -> None:
    """``write_config_txt`` removes a stale file when no remora MCU exists."""

    stale = tmp_path / "config.txt"
    stale.write_text("stale payload\n", encoding="utf-8")
    cfg = _write_profile(
        tmp_path,
        "[mcu rs485]\nconnection: rs485\ninterface: com0\n"
        + _stepper_section("x"),
    )
    graph = parse_config(cfg)
    write_config_txt(stale, graph, "test")
    assert not stale.exists()


def test_write_config_txt_emits_payload_when_single_remora(tmp_path: Path) -> None:
    """Single remora → payload lands on disk."""

    target = tmp_path / "config.txt"
    cfg = _write_profile(
        tmp_path,
        "[mcu]\nconnection: remora-spi\nboard: BIGTREETECH OCTOPUS\n"
        + _stepper_section("x"),
    )
    graph = parse_config(cfg)
    write_config_txt(target, graph, "test")
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["Board"] == "BIGTREETECH OCTOPUS"
    assert any(m["Type"] == "Stepgen" for m in payload["Modules"])


# --------------------------------------------------------------------- #
# Pin routing — config.txt only emits pins on the resolved remora MCU   #
# --------------------------------------------------------------------- #


def test_config_txt_emits_pins_on_remora_mcu_only(tmp_path: Path) -> None:
    """Pins on a non-remora MCU are silently skipped from ``config.txt``."""

    cfg = _write_profile(
        tmp_path,
        # Single remora MCU + a non-remora companion.
        "[mcu]\nconnection: remora-spi\nboard: BIGTREETECH OCTOPUS\n"
        "[mcu rs485_com]\nconnection: rs485\ninterface: com0\n"
        # X is fully qualified to the remora MCU.
        + _stepper_section(
            "x",
            pins=("mcu:PF11", "mcu:PG3", "mcu:!PG5"),
        )
        + _stepper_section(
            "y",
            pins=("rs485_com:PA1", "rs485_com:PA2", "rs485_com:!PA3"),
            rotation_distance=40.0,
        ),
    )
    graph = parse_config(cfg)
    payload = build_config_txt(graph, "test")
    stepgens = [m for m in payload["Modules"] if m["Type"] == "Stepgen"]
    # Only the X stepper survives: Y's pins all carry the rs485_com qualifier.
    assert len(stepgens) == 1
    assert stepgens[0]["Name"] == "stepper_x"
    assert stepgens[0]["Step Pin"] == "PF_11"


def test_config_txt_emits_qualifier_when_all_pins_target_remora(
    tmp_path: Path,
) -> None:
    """A stepper fully qualified with the remora MCU's name flows through."""

    cfg = _write_profile(
        tmp_path,
        "[mcu]\nconnection: remora-spi\nboard: BIGTREETECH OCTOPUS\n"
        "[mcu rs485_com]\nconnection: rs485\ninterface: com0\n"
        + _stepper_section(
            "x",
            pins=("mcu:PF11", "mcu:PG3", "mcu:!PG5"),
        )
        + _stepper_section(
            "y",
            pins=("mcu:PF12", "mcu:PG4", "mcu:!PG6"),
        ),
    )
    graph = parse_config(cfg)
    payload = build_config_txt(graph, "test")
    stepgens = [m for m in payload["Modules"] if m["Type"] == "Stepgen"]
    assert len(stepgens) == 2
    by_name = {m["Name"]: m for m in stepgens}
    assert by_name["stepper_x"]["Step Pin"] == "PF_11"
    assert by_name["stepper_y"]["Step Pin"] == "PF_12"


def test_config_txt_routes_qualified_pins_to_their_mcu(tmp_path: Path) -> None:
    """A pin qualified with the remora MCU's name flows into ``config.txt``."""

    cfg = _write_profile(
        tmp_path,
        "[mcu]\nconnection: remora-spi\nboard: BIGTREETECH OCTOPUS\n"
        "[mcu rs485_com]\nconnection: rs485\ninterface: com0\n"
        + _stepper_section(
            "x",
            pins=("mcu:PF11", "mcu:PG3", "mcu:!PG5"),
        ),
    )
    graph = parse_config(cfg)
    payload = build_config_txt(graph, "test")
    stepgens = [m for m in payload["Modules"] if m["Type"] == "Stepgen"]
    assert len(stepgens) == 1
    assert stepgens[0]["Step Pin"] == "PF_11"
    assert stepgens[0]["Direction Pin"] == "PG_3"
    assert stepgens[0]["Enable Pin"] == "PG_5"


def test_config_txt_emits_fan_only_for_remora_pins(tmp_path: Path) -> None:
    """Standalone fans get a PWM module only when their pin targets the remora MCU."""

    cfg = _write_profile(
        tmp_path,
        "[mcu]\nconnection: remora-spi\nboard: BIGTREETECH OCTOPUS\n"
        "[mcu rs485_com]\nconnection: rs485\ninterface: com0\n"
        # Qualified to the remora MCU — survives.
        "[fan_generic part_cooling]\npin: mcu:PA8\n"
        # Qualified to the rs485 companion — skipped.
        "[fan_generic hot_end]\npin: rs485_com:PA9\n",
    )
    graph = parse_config(cfg)
    payload = build_config_txt(graph, "test")
    pwms = [m for m in payload["Modules"] if m["Type"] == "PWM"]
    fan_names = {m["Name"] for m in pwms}
    assert "pwm_fan_generic_part_cooling" in fan_names
    assert "pwm_fan_generic_hot_end" not in fan_names


def test_config_txt_bare_pins_skipped_when_multiple_mcus(tmp_path: Path) -> None:
    """When multiple MCUs are declared, bare pins are ambiguous and skipped.

    Two distinct pin sets — one bare and one fully qualified — are
    passed through; the bare ones must not survive because the
    emitter cannot tell which MCU they belong to.
    """

    cfg = _write_profile(
        tmp_path,
        "[mcu]\nconnection: remora-spi\nboard: BIGTREETECH OCTOPUS\n"
        "[mcu rs485_com]\nconnection: rs485\ninterface: com0\n"
        # Z is bare — must be dropped
        + _stepper_section("z", pins=("PF13", "PG7", "!PG8"))
        # Y is fully qualified and survives
        + _stepper_section(
            "y",
            pins=("mcu:PF11", "mcu:PG3", "mcu:!PG5"),
        ),
    )
    graph = parse_config(cfg)
    payload = build_config_txt(graph, "test")
    stepgens = [m for m in payload["Modules"] if m["Type"] == "Stepgen"]
    names = sorted(m["Name"] for m in stepgens)
    # Only the fully-qualified Y joint survives — the bare Z joint is
    # ambiguous and dropped at emit time.
    assert names == ["stepper_y"]


def test_config_txt_emits_digital_pin_only_for_remora_endstop(tmp_path: Path) -> None:
    """An endstop pin on a non-remora MCU is dropped from config.txt."""

    cfg = _write_profile(
        tmp_path,
        "[mcu]\nconnection: remora-spi\nboard: BIGTREETECH OCTOPUS\n"
        "[mcu rs485_com]\nconnection: rs485\ninterface: com0\n"
        # X survives: every pin (incl. endstop) is owned by the remora MCU.
        + _stepper_section(
            "x",
            endstop="mcu:^PC0",
            pins=("mcu:PF11", "mcu:PG3", "mcu:!PG5"),
        )
        # Y is dropped entirely: every pin routes to the rs485 companion.
        + _stepper_section(
            "y",
            endstop="rs485_com:^PC1",
            pins=("rs485_com:PA1", "rs485_com:PA2", "rs485_com:!PA3"),
        ),
    )
    graph = parse_config(cfg)
    payload = build_config_txt(graph, "test")
    digital = [m for m in payload["Modules"] if m["Type"] == "Digital Pin"]
    pins = [m["Pin"] for m in digital]
    # X's endstop survives on the remora board; Y's is dropped.
    assert "PC_0" in pins
    assert "PC_1" not in pins


# --------------------------------------------------------------------- #
# hardware.json — `mcus` list exposed                                    #
# --------------------------------------------------------------------- #


def test_hardware_json_exposes_mcus_list(tmp_path: Path) -> None:
    cfg = _write_profile(
        tmp_path,
        "[mcu]\nconnection: remora-spi\nboard: BIGTREETECH OCTOPUS\n"
        "[mcu rs485_com]\nconnection: rs485\ninterface: com0\n"
        + _stepper_section("x"),
    )
    graph = parse_config(cfg)
    payload = build_hardware_json(graph, "test")
    assert "mcus" in payload
    ids = sorted(m["id"] for m in payload["mcus"])
    assert ids == ["mcu", "rs485_com"]
    remora_mcu = next(m for m in payload["mcus"] if m["id"] == "mcu")
    assert remora_mcu["connection"] == "remora-spi"
    assert remora_mcu["is_remora"] is True
    rs485 = next(m for m in payload["mcus"] if m["id"] == "rs485_com")
    assert rs485["is_remora"] is False


def test_hardware_json_mcus_empty_when_no_mcu(tmp_path: Path) -> None:
    cfg = _write_profile(
        tmp_path,
        "[printer]\nkinematics: cartesian\nmax_velocity: 300\n"
        + _stepper_section("x"),
    )
    graph = parse_config(cfg)
    payload = build_hardware_json(graph, "test")
    assert payload["mcus"] == []


# --------------------------------------------------------------------- #
# HAL — multi-MCU comment                                               #
# --------------------------------------------------------------------- #


def test_hal_includes_multi_mcu_note_for_non_remora_transports(
    tmp_path: Path,
) -> None:
    """A profile with a non-remora MCU emits a one-line diagnostic comment."""

    cfg = _write_profile(
        tmp_path,
        "[mcu]\nconnection: remora-spi\nboard: BIGTREETECH OCTOPUS\n"
        "[mcu rs485_com]\nconnection: rs485\ninterface: com0\n"
        + _stepper_section("x"),
    )
    graph = parse_config(cfg)
    rendered = build_hal_from_graph(graph)
    assert "Multi-MCU note" in rendered
    assert "rs485_com" in rendered


def test_hal_omits_multi_mcu_note_for_single_mcu(tmp_path: Path) -> None:
    """A single-MCU profile produces the unchanged HAL output."""

    cfg = _write_profile(
        tmp_path,
        "[mcu]\nconnection: remora-spi\nboard: BIGTREETECH OCTOPUS\n"
        + _stepper_section("x"),
    )
    graph = parse_config(cfg)
    rendered = build_hal_from_graph(graph)
    assert "Multi-MCU note" not in rendered


def test_hal_omits_multi_mcu_note_when_only_remora_mcus(
    tmp_path: Path,
) -> None:
    """Multiple remora MCUs are already warned elsewhere; no HAL comment."""

    cfg = _write_profile(
        tmp_path,
        "[mcu a]\nconnection: remora-spi\nboard: BIGTREETECH OCTOPUS\n"
        "[mcu b]\nconnection: remora-eth\nboard: SKR2\n"
        + _stepper_section("x"),
    )
    graph = parse_config(cfg)
    rendered = build_hal_from_graph(graph)
    assert "Multi-MCU note" not in rendered


# --------------------------------------------------------------------- #
# Round-trip — goal snapshot stays intact                                #
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "connection",
    sorted(REMORA_CONNECTION_TYPES),
)
def test_remora_connection_types_are_single_payload(
    tmp_path: Path,
    connection: str,
) -> None:
    """All remora connections funnel through the same payload path."""

    cfg = _write_profile(
        tmp_path,
        f"[mcu]\nconnection: {connection}\nboard: BIGTREETECH OCTOPUS\n"
        + _stepper_section("x"),
    )
    graph = parse_config(cfg)
    payload = build_config_txt(graph, "test")
    assert payload["Board"] == "BIGTREETECH OCTOPUS"
    assert any(m["Type"] == "Stepgen" for m in payload["Modules"])
