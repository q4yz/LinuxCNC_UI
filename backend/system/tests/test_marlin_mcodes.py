"""Marlin heater / fan M-codes: REMAP lines, subroutines, helper M-codes,
written by the machine generator (`marlin_mcodes`)."""
from __future__ import annotations

import ast

from MachineConfigParser import MachineConfigParser
from services.machineconfig.hardware_json_generator import build_hardware_json
from services.machinetemplates.marlin_mcodes import marlin_support

PRINTER = open("tests/fixtures/profiles/full_klipper.cfg").read()


def _payload(cfg=PRINTER):
    return build_hardware_json(MachineConfigParser().parse_string(cfg), "m")


def test_remaps_for_a_printer():
    support = marlin_support(_payload())
    assert support.remaps == [
        "REMAP=M104 modalgroup=10 argspec=pq ngc=m104",
        "REMAP=M109 modalgroup=10 argspec=pq ngc=m109",
        "REMAP=M140 modalgroup=10 argspec=p ngc=m140",
        "REMAP=M190 modalgroup=10 argspec=p ngc=m190",
        "REMAP=M106 modalgroup=10 argspec=pq ngc=m106",
        "REMAP=M107 modalgroup=10 argspec=q ngc=m107",
    ]
    assert set(support.subroutines) == {"m104.ngc", "m109.ngc", "m140.ngc", "m190.ngc", "m106.ngc", "m107.ngc"}
    assert "M181 P#<temp> Q-1" in support.subroutines["m190.ngc"]
    assert "M180 P#<temp> Q#<heater>" in support.subroutines["m104.ngc"]
    assert set(support.mcodes) == {"M180", "M181", "M182"}


def test_helpers_are_python_with_the_machines_ids():
    support = marlin_support(_payload())
    for name, source in support.mcodes.items():
        assert source.startswith("#!/usr/bin/env python3")
        ast.parse(source)
    m181 = support.mcodes["M181"]
    assert 'EXTRUDERS = [["heater_extruder", "extruder"]]' in m181
    assert 'BED = ["heater_bed", "bed"]' in m181
    assert "MODE = 'wait'" in m181
    # A heater's placeholder fan shares its pin: never an M106 target.
    assert 'FANS = ["fan"]' in support.mcodes["M182"]


def test_nothing_for_a_machine_without_heaters_or_fans():
    cfg = "[mcu]\nconnection: remora-spi\n\n[stepper_x]\nstep_pin: PF13\ndir_pin: PF12\nposition_endstop: 0\nposition_max: 200\n\n[estop]\n"
    support = marlin_support(_payload(cfg))
    assert not support.enabled and support.mcodes == {}


def test_generated_machine(tmp_path):
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import generate_machine_templates

    profiles, machines = tmp_path / "profiles", tmp_path / "machines"
    profiles.mkdir()
    machines.mkdir()
    (profiles / "printer.cfg").write_text(PRINTER, encoding="utf-8")
    generate_machine_templates(
        "printer.cfg",
        config_service=ConfigFileService(root=profiles),
        machine_service=MachineFileService(root=machines),
    )
    configs = machines / "printer" / "configs"
    ini = (configs / "machine.ini").read_text()
    assert "REMAP=M109 modalgroup=10 argspec=pq ngc=m109" in ini
    assert any(l.startswith("USER_M_PATH = ") and l.endswith(":mcodes") for l in ini.splitlines())
    assert any(l.startswith("SUBROUTINE_PATH = ") and l.endswith(":subroutines") for l in ini.splitlines())
    assert (configs / "subroutines" / "m109.ngc").is_file()
    helper = configs / "mcodes" / "M181"
    assert helper.is_file() and helper.stat().st_mode & 0o111
