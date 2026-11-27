"""The probe latch (Remora "Probe Latch"): generated when the probe and Z's
step generator are on the same Remora SPI board, not otherwise; [probe]
second_speed / second_retract reach hardware.json."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from MachineConfigParser import InvalidValueError, MachineConfigParser
from services.machineconfig.hardware_json_generator import build_hardware_json

FIXTURES = Path("tests/fixtures/profiles")
PRINTER = (FIXTURES / "full_klipper.cfg").read_text()
CAN = (FIXTURES / "corexy_can_extruder.cfg").read_text()  # no [probe]


def generate(tmp_path: Path, cfg: str) -> Path:
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import generate_machine_templates

    profiles, machines = tmp_path / "profiles", tmp_path / "machines"
    profiles.mkdir()
    machines.mkdir()
    (profiles / "m.cfg").write_text(cfg, encoding="utf-8")
    generate_machine_templates("m.cfg", config_service=ConfigFileService(root=profiles),
                               machine_service=MachineFileService(root=machines))
    return machines / "m" / "configs"


def modules(configs: Path) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for path in configs.glob("config*.txt"):
        found += json.loads(path.read_text(encoding="utf-8")).get("Modules") or []
    return found


def test_probe_on_z_s_board_gets_a_latch(tmp_path):
    configs = generate(tmp_path, PRINTER + "\n[probe]\npin: ^!PG13\n")
    latch = [m for m in modules(configs) if m.get("Type") == "Probe Latch"]
    assert len(latch) == 1
    module = latch[0]
    assert module["Thread"] == "Base" and module["Pin"] == "PG_13" and module["Joint Number"] == 2
    assert module["Invert"] == "True" and module["Modifier"] == "Pull Up"
    # the probe keeps its Digital Pin input (LinuxCNC's G38 stops on it)
    assert any(m.get("Type") == "Digital Pin" and m.get("Pin") == "PG_13" for m in modules(configs))
    hal = (configs / "machine.hal").read_text(encoding="utf-8")
    assert f"net probe-latch <= remora.PV.{module['PV[i]']}" in hal


def test_no_probe_no_latch(tmp_path):
    configs = generate(tmp_path, CAN)
    assert not [m for m in modules(configs) if m.get("Type") == "Probe Latch"]
    assert "probe-latch" not in (configs / "machine.hal").read_text(encoding="utf-8")


def test_the_router_adds_a_latch_only_when_asked():
    """A probe whose board does not carry Z (HalAssembler._probe_latch_joint
    gives None) gets only its Digital Pin."""
    from mappers.machineconfig import PinStringMapper
    from models.machineconfig.HalFragmentModels import PinRequest, PinRole
    from services.halcompiler.mcus.RemoraRouterMapper import RemoraRouterMapper

    def route(latch_joint):
        request = PinRequest(signal="probe-in", role=PinRole.DIGITAL_IN, pin=PinStringMapper.from_string("PG13"),
                             owner="probe", latch_joint=latch_joint)
        return [m.module.get("Type") for m in RemoraRouterMapper.route([request]).firmware_modules]

    assert route(None) == ["Digital Pin"]
    assert route(2) == ["Digital Pin", "Probe Latch"]


def test_two_pass_settings_reach_hardware_json():
    def probe(extra: str):
        return build_hardware_json(MachineConfigParser().parse_string(PRINTER + "\n[probe]\npin: PG13\n" + extra),
                                   "m")["probe"]

    assert "second_speed" not in probe("")  # the backend's defaults
    assert probe("second_speed: 0.5\nsecond_retract: 1.5\n")["second_speed"] == 0.5
    assert probe("second_speed: 0\n")["second_speed"] == 0.0  # one pass
    with pytest.raises(InvalidValueError):
        probe("second_retract: 0\n")
