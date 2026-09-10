"""Tests for the machine template generator.

Covers:

* ``build_pin_catalog`` introspection of the frozen pin-container
  dataclasses (readonly / readwrite / static / unconnected / nested).
* ``render_ini_template`` / ``render_hal_template`` output contracts.
* ``generate_machine_templates``: artifact set, machine-exists guard,
  confirm_override, nested target folders, path-safety.
* The ``/machines/*`` router surface (tree, generate + 409 flow, CRUD).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests._module_app_factory import build_module_app

PROFILE_BODY = (
    "[printer]\n"
    "kinematics: cartesian\n"
    "max_velocity: 300\n\n"
    "[stepper_x]\n"
    "step_pin: PF13\n"
    "dir_pin: PF12\n"
    "enable_pin: !PF14\n"
    "microsteps: 16\n"
    "rotation_distance: 40\n"
    "position_endstop: 0\n"
    "position_max: 300\n"
)


# ---------------------------------------------------------------------- #
# Fixtures                                                                #
# ---------------------------------------------------------------------- #

@pytest.fixture()
def isolated_roots(tmp_path):
    """Fresh profiles/ + machines/ roots plus seeded profile."""
    profiles = tmp_path / "profiles"
    machines = tmp_path / "machines"
    profiles.mkdir()
    machines.mkdir()
    (profiles / "my_machine.cfg").write_text(PROFILE_BODY, encoding="utf-8")
    return {"root": tmp_path, "profiles": profiles, "machines": machines}


@pytest.fixture()
def machine_app(tmp_data_root, clean_env, isolated_roots, monkeypatch):
    """Machineconfig app with the router-level factories re-bound to
    the isolated roots (deterministic — no real-tree access)."""
    from domain_file_services import ConfigFileService, MachineFileService
    import routers.machineconfig as router_module

    config_service = ConfigFileService(root=isolated_roots["profiles"])
    machine_service = MachineFileService(root=isolated_roots["machines"])
    monkeypatch.setattr(router_module, "get_config_service", lambda: config_service)
    monkeypatch.setattr(router_module, "get_machine_service", lambda: machine_service)

    app = build_module_app("machineconfig", tmp_data_root)
    return app


# ---------------------------------------------------------------------- #
# Pin catalog                                                             #
# ---------------------------------------------------------------------- #

def _spindle_container():
    from dtos.EStopDto import EStopPin
    from dtos.pins.HalPin import HalDataType
    from dtos.pins.ReadOnlyDynamicHalPin import ReadOnlyDynamicHalPin
    from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
    from dtos.pins.StaticHalPin import StaticHalPin
    from dtos.tools.SpindleDigitalDto import SpindleDigitalPins

    return (
        SpindleDigitalPins(
            id="spindle_digital",
            spindle_at_speed=ReadOnlyDynamicHalPin("spindle-at-speed", HalDataType.BIT, ""),
            actual_rpm=ReadOnlyDynamicHalPin("rpm-out", HalDataType.FLOAT, ""),
            min_rpm=StaticHalPin(0),
            max_rpm=StaticHalPin(24000),
            override=ReadWriteDynamicHalPin("override", HalDataType.S32, ""),
        ),
        EStopPin("estop", ReadWriteDynamicHalPin("estop", HalDataType.BIT, "")),
    )


def test_pin_catalog_introspects_directions():
    from services.machinetemplates import build_pin_catalog

    spindle, estop = _spindle_container()
    catalog = build_pin_catalog(
        tool_containers=[spindle],
        sensor_containers=[],
        state_containers=[estop],
    )

    assert catalog.total_pins() == 14
    assert catalog.groups() == ["tools", "state"]

    tools = catalog.for_group("tools")[0]
    assert tools.container == "SpindleDigitalPins"
    assert tools.owner_id == "spindle_digital"

    by_field = {p.field: p for p in tools.pins}

    at_speed = by_field["spindle_at_speed"]
    assert at_speed.kind == "readonly"
    assert at_speed.direction == "in"
    assert at_speed.pin_name == "webgui.spindle-at-speed"
    assert at_speed.hal_type == "BIT"
    assert "vfdmod.spindle-at-speed" in at_speed.connect_hint

    override_pin = by_field["override"]
    assert override_pin.kind == "readwrite"
    assert override_pin.direction == "out"
    assert override_pin.short_pin == "override"

    max_rpm = by_field["max_rpm"]
    assert max_rpm.kind == "static"
    assert max_rpm.value == "24000"
    assert max_rpm.direction == ""

    # Fields the runtime mapper left blank stay listed as placeholders.
    assert by_field["spindle_forward"].kind == "unconnected"

    state = catalog.for_group("state")[0]
    estop_pin = state.pins[0]
    assert estop_pin.field == "pressed"
    assert estop_pin.direction == "out"
    assert estop_pin.pin_name == "webgui.estop"


def test_pin_catalog_flattens_nested_heater():
    from dtos.pins.HalPin import HalDataType
    from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
    from dtos.tools.ExtruderDto import ExtruderPins
    from dtos.tools.HeaterDto import HeaterPins
    from services.machinetemplates import build_pin_catalog

    container = ExtruderPins(
        id="extruder",
        heater=HeaterPins(
            id="heater",
            target_temperature=ReadWriteDynamicHalPin("target-temperature", HalDataType.FLOAT, ""),
        ),
        position=ReadWriteDynamicHalPin("extruder_position", HalDataType.FLOAT, ""),
    )
    catalog = build_pin_catalog(
        tool_containers=[container], sensor_containers=[], state_containers=[]
    )
    fields = {p.field: p for p in catalog.containers[0].pins}
    assert "heater.target_temperature" in fields
    assert "position" in fields
    # Nested leaves keep their own container class for hint lookup.
    assert fields["heater.target_temperature"].container == "HeaterPins"
    assert "PID" in fields["heater.target_temperature"].connect_hint


def test_pin_catalog_default_uses_active_hardware_json(monkeypatch, isolated_roots):
    """The default source is the active hardware.json via the shared layer.

    The pre-split version read the machine services' cached pin
    containers; those services now live in the machine backend. The
    catalog instead rebuilds containers from the config mappers, so
    patching the default builder drives the default path.
    """
    import services.machinetemplates.pin_catalog as pin_catalog_mod
    from services.machinetemplates import build_pin_catalog

    spindle, estop = _spindle_container()

    def fake_build_default_containers():
        return [spindle], [], [estop]

    monkeypatch.setattr(
        pin_catalog_mod, "_build_default_containers", fake_build_default_containers
    )

    catalog = build_pin_catalog(sensor_containers=[])
    assert any(c.container == "SpindleDigitalPins" for c in catalog.containers)
    assert any(c.container == "EStopPin" for c in catalog.containers)


# ---------------------------------------------------------------------- #
# Template renderers                                                      #
# ---------------------------------------------------------------------- #

def test_render_hal_template_is_inert_documentation():
    from services.machinetemplates import build_pin_catalog, render_hal_template

    spindle, estop = _spindle_container()
    catalog = build_pin_catalog(
        tool_containers=[spindle], sensor_containers=[], state_containers=[estop]
    )
    text = render_hal_template("my_machine", catalog)

    assert "TEMPLATE - NOT FUNCTIONAL" in text
    assert "Machine: my_machine" in text
    # Every live line is a comment (inert template).
    live = [l for l in text.splitlines() if l and not l.startswith("#")]
    assert live == []
    assert "net spindle_at_speed => webgui.spindle-at-speed" in text
    assert "net override <= webgui.override" in text
    assert "static config constant = 24000" in text
    assert "config.txt" in text  # the do-not-flash note


def test_render_hal_template_appendix_mode_drops_the_standalone_framing():
    """``standalone=False`` is what ``_render_machine_hal`` appends after
    real compiled HAL — it must not claim the whole file is inert."""
    from services.machinetemplates import build_pin_catalog, render_hal_template

    spindle, estop = _spindle_container()
    catalog = build_pin_catalog(
        tool_containers=[spindle], sensor_containers=[], state_containers=[estop]
    )
    text = render_hal_template("my_machine", catalog, standalone=False)

    assert "TEMPLATE - NOT FUNCTIONAL" not in text
    assert "WEBGUI PIN REFERENCE" in text
    assert "Next steps" not in text
    # The per-pin catalog body itself is unaffected.
    assert "net spindle_at_speed => webgui.spindle-at-speed" in text
    # Still entirely inert — an appendix must never look executable.
    live = [l for l in text.splitlines() if l and not l.startswith("#")]
    assert live == []


def _axis(letter, *joint_numbers, max_velocity=50.0, max_limit=300.0):
    from models.machineconfig.linuxcnc_models import Axis, Joint

    joints = [
        Joint(joint_number=n, axis_letter=letter, max_velocity=max_velocity, max_limit=max_limit)
        for n in joint_numbers
    ]
    return Axis(
        letter=letter,
        joints=joints,
        max_velocity=max_velocity,
        max_acceleration=400.0,
        min_limit=0.0,
        max_limit=max_limit,
    )


def test_render_ini_template_is_live_and_loadable():
    """The rendered INI is a real, loadable config — not a commented
    skeleton — with every axis/joint section populated live."""
    from services.machinetemplates import render_ini_template

    axes = [_axis("X", 0), _axis("Y", 1), _axis("Z", 2)]
    text = render_ini_template("my_machine", axes)

    assert "MACHINE = my_machine" in text
    assert "DEBUG = 0" in text
    assert "VERSION = 1.1" in text
    assert "[KINS]" in text
    assert "JOINTS = 3" in text
    assert "KINEMATICS = trivkins coordinates=XYZ" in text
    assert "[HAL]" in text
    assert "HALFILE = machine.hal" in text
    assert "HALFILE = custom.hal" in text
    assert "POSTGUI_HALFILE = postgui_call_list.hal" in text
    assert "[APPLICATIONS]" in text
    assert "[EMCIO]" in text
    assert "TOOL_TABLE = tool.tbl" in text

    # Axis/joint sections are live (uncommented) with real values.
    assert "[AXIS_X]" in text
    assert "[JOINT_0]" in text
    assert "MAX_VELOCITY = 50.0" in text
    for line in text.splitlines():
        assert not line.startswith("# ["), f"section line is commented out: {line!r}"


def test_render_ini_template_multi_joint_axis_repeats_letter():
    """A dual-motor axis (e.g. a gantry Y) emits one [JOINT_N] per
    motor and repeats its letter in the trivkins coordinates string."""
    from services.machinetemplates import render_ini_template

    axes = [_axis("X", 0), _axis("Y", 1, 2), _axis("Z", 3)]
    text = render_ini_template("gantry", axes)

    assert "JOINTS = 4" in text
    assert "KINEMATICS = trivkins coordinates=XYYZ" in text
    assert "COORDINATES = XYYZ" in text
    assert "[JOINT_1]" in text
    assert "[JOINT_2]" in text


def test_render_ini_template_emits_a_pid_section_per_pid_heater():
    """Bug: `HeaterHalMapper` writes `setp PID-<id>.KP [<SECTION>]
    PID_KP` into machine.hal — an ini-var *reference*. Without a
    matching `[<SECTION>]` block in machine.ini every gain silently
    resolves to nothing."""
    from services.machinetemplates import render_ini_template

    tools = [
        {
            "id": "heater_bed",
            "type": "heated_bed",
            "control": "pid",
            "pid_kp": 20.0,
            "pid_ki": 1.5,
            "pid_kd": 5.0,
            "min_temp": 0.0,
            "max_temp": 130.0,
        },
        {
            "id": "heater_extruder",
            "type": "extruder",
            "control": "pid",
            "pid_kp": 22.2,
            "pid_ki": 1.08,
            "pid_kd": 114.0,
            "min_temp": 0.0,
            "max_temp": 300.0,
        },
    ]
    text = render_ini_template("printer", [_axis("X", 0)], tools)

    assert "[HEATER_BED]" in text
    assert "PID_KP = 20.0" in text
    assert "PID_KI = 1.5" in text
    assert "PID_KD = 5.0" in text
    assert "PID_SPMIN = 0.0" in text
    assert "PID_SPMAX = 130.0" in text
    assert "PID_CVMIN = 0.0" in text
    assert "PID_CVMAX = 100.0" in text
    assert "PID_DIR = 0" in text
    assert "PID_PONM = 1" in text

    assert "[HEATER_EXTRUDER]" in text
    assert "PID_KP = 22.2" in text
    assert "PID_SPMAX = 300.0" in text


def test_render_ini_template_skips_watermark_heaters():
    """`HeaterHalMapper._watermark_loop` uses literals throughout — no
    ini-var references, so no section is needed (or emitted)."""
    from services.machinetemplates import render_ini_template

    tools = [{"id": "heater_bed", "type": "heated_bed", "control": "watermark"}]
    text = render_ini_template("printer", [_axis("X", 0)], tools)
    assert "[HEATER_BED]" not in text


def test_render_ini_template_without_tools_is_unaffected():
    """The `tools` parameter is additive — omitting it entirely (the
    pre-existing call shape) must render exactly as before."""
    from services.machinetemplates import render_ini_template

    text = render_ini_template("printer", [_axis("X", 0)])
    assert "PID_" not in text


# ---------------------------------------------------------------------- #
# generate_machine_templates                                              #
# ---------------------------------------------------------------------- #

def test_generate_writes_full_template_set(isolated_roots):
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import (
        GENERATED_FILES,
        build_pin_catalog,
        generate_machine_templates,
    )

    spindle, estop = _spindle_container()
    catalog = build_pin_catalog(
        tool_containers=[spindle], sensor_containers=[], state_containers=[estop]
    )
    result = generate_machine_templates(
        "my_machine.cfg",
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
        catalog=catalog,
    )

    assert result.machine == "my_machine"
    assert sorted(Path(f).name for f in result.files) == sorted(GENERATED_FILES)

    configs = isolated_roots["machines"] / "my_machine" / "configs"
    # Source copy is verbatim.
    assert (configs / "machine.cfg").read_text(encoding="utf-8") == PROFILE_BODY
    # hardware.json is the real contract.
    import json

    payload = json.loads((configs / "hardware.json").read_text(encoding="utf-8"))
    assert payload["machine"] == "my_machine"
    assert [a["id"] for a in payload["axes"]] == ["x"]
    # No Remora flash payload.
    assert not (configs / "config.txt").exists()

    # machine.ini is live and loadable — not the old commented skeleton.
    ini = (configs / "machine.ini").read_text(encoding="utf-8")
    assert "MACHINE = my_machine" in ini
    assert "[AXIS_X]" in ini
    assert "[JOINT_0]" in ini

    # custom.hal always loads webgui and sources webgui_connections.hal.
    custom_hal = (configs / "custom.hal").read_text(encoding="utf-8")
    assert "loadusr -W -n webgui" in custom_hal
    assert custom_hal.strip().endswith("source webgui_connections.hal")

    # webgui_connections.hal ships as a starter file.
    assert (configs / "webgui_connections.hal").exists()
    assert (configs / "tool.tbl").exists()
    assert (configs / "postgui_call_list.hal").exists()


def test_generate_falls_back_to_the_catalog_when_the_machine_does_not_compile(isolated_roots):
    """`PROFILE_BODY` declares no `[mcu]` at all — `E_NO_MCU` blocks
    compilation. The old catalog-only behaviour must survive exactly:
    a fully-commented file, never a crash, never half-real HAL."""
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import generate_machine_templates

    generate_machine_templates(
        "my_machine.cfg",
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
    )

    hal = (isolated_roots["machines"] / "my_machine" / "configs" / "machine.hal").read_text(
        encoding="utf-8"
    )
    assert "could not generate real wiring" in hal
    assert "E_NO_MCU" in hal
    assert "TEMPLATE - NOT FUNCTIONAL" in hal
    live = [l for l in hal.splitlines() if l.strip() and not l.strip().startswith("#")]
    assert live == []


def test_generate_writes_real_compiled_hal_when_the_machine_validates(isolated_roots):
    """A profile with a real `[mcu]` compiles — `machine.hal` becomes
    genuinely functional HAL, not a commented catalog, with the pin
    catalog trailing as a reference appendix instead."""
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import generate_machine_templates

    profile = (
        "[mcu]\n"
        "connection: remora-spi\n\n"
        "[printer]\n"
        "kinematics: cartesian\n"
        "max_velocity: 300\n\n"
        "[stepper_x]\n"
        "step_pin: PF13\n"
        "dir_pin: PF12\n"
        "enable_pin: !PF14\n"
        "microsteps: 16\n"
        "rotation_distance: 40\n"
        "position_endstop: 0\n"
        "position_max: 300\n"
    )
    (isolated_roots["profiles"] / "compilable.cfg").write_text(profile, encoding="utf-8")

    generate_machine_templates(
        "compilable.cfg",
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
    )

    hal = (isolated_roots["machines"] / "compilable" / "configs" / "machine.hal").read_text(
        encoding="utf-8"
    )
    assert "loadrt remora-spi" in hal
    assert "remora.joint.0.scale" in hal
    # Real, live lines exist now — not everything commented.
    live = [l for l in hal.splitlines() if l.strip() and not l.strip().startswith("#")]
    assert live
    # The webgui pin reference still trails, in its appendix framing.
    assert "WEBGUI PIN REFERENCE" in hal
    assert "TEMPLATE - NOT FUNCTIONAL" not in hal

    # The Remora firmware payload is written too, keyed by MCU id.
    configs = isolated_roots["machines"] / "compilable" / "configs"
    config_txt = (configs / "config_mcu.txt").read_text(encoding="utf-8")
    assert '"Joint Number": 0' in config_txt


def test_generate_numbers_the_extruder_joint_correctly_and_writes_its_pid_section(
    isolated_roots,
):
    """End-to-end regression for two real bugs found in the generated
    `machine.ini`: the extruder joint was always numbered 0 (colliding
    with X's own `[JOINT_0]`) instead of continuing the X/Y/Z
    sequence, and no `[HEATER_EXTRUDER]` PID section existed at all —
    `machine.hal`'s `setp PID-heater_extruder.KP [HEATER_EXTRUDER]
    PID_KP` referenced a section that was never written."""
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import generate_machine_templates

    profile = (
        "[mcu]\nconnection: remora-spi\n\n"
        "[stepper_x]\nstep_pin: PF13\ndir_pin: PF12\nrotation_distance: 40\nposition_max: 300\n\n"
        "[stepper_y]\nstep_pin: PG0\ndir_pin: PG1\nrotation_distance: 40\nposition_max: 300\n\n"
        "[stepper_z]\nstep_pin: PG2\ndir_pin: PG3\nrotation_distance: 40\nposition_max: 300\n\n"
        "[extruder]\n"
        "step_pin: PC9\ndir_pin: PC8\nrotation_distance: 33.5\n"
        "heater_pin: PE3\nsensor_pin: PA1\ncontrol: pid\n"
        "pid_Kp: 22.2\npid_Ki: 1.08\npid_Kd: 114\nmin_temp: 0\nmax_temp: 250\n"
    )
    (isolated_roots["profiles"] / "printer.cfg").write_text(profile, encoding="utf-8")

    generate_machine_templates(
        "printer.cfg",
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
    )

    configs = isolated_roots["machines"] / "printer" / "configs"
    ini = (configs / "machine.ini").read_text(encoding="utf-8")

    assert "[JOINT_0]" in ini
    assert "[JOINT_1]" in ini
    assert "[JOINT_2]" in ini
    assert "[JOINT_3]" in ini
    # Exactly one of each — the old bug produced two `[JOINT_0]` blocks.
    assert ini.count("[JOINT_0]") == 1
    assert ini.count("[JOINT_3]") == 1

    assert "[HEATER_EXTRUDER]" in ini
    assert "PID_KP = 22.2" in ini
    assert "PID_SPMAX = 250.0" in ini

    hal = (configs / "machine.hal").read_text(encoding="utf-8")
    assert "setp PID-heater_extruder.KP [HEATER_EXTRUDER]PID_KP" in hal
    # The section this line references really does exist in machine.ini.
    assert "[HEATER_EXTRUDER]" in ini


def test_generate_gives_each_remora_board_its_own_config_txt(isolated_roots):
    """Two Remora MCUs on one machine — a second board's firmware
    payload must never overwrite the first's `config.txt`."""
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import generate_machine_templates

    profile = (
        "[mcu mcu_a]\n"
        "connection: remora-spi\n\n"
        "[mcu mcu_b]\n"
        "connection: remora-spi\n\n"
        "[stepper_x]\n"
        "step_pin: mcu_a:PF13\n"
        "dir_pin: mcu_a:PF12\n"
        "enable_pin: mcu_a:PF14\n"
        "rotation_distance: 40\n"
        "position_max: 300\n\n"
        "[stepper_y]\n"
        "step_pin: mcu_b:PG0\n"
        "dir_pin: mcu_b:PG1\n"
        "enable_pin: mcu_b:PF15\n"
        "rotation_distance: 40\n"
        "position_max: 300\n"
    )
    (isolated_roots["profiles"] / "dual_board.cfg").write_text(profile, encoding="utf-8")

    result = generate_machine_templates(
        "dual_board.cfg",
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
    )

    configs = isolated_roots["machines"] / "dual_board" / "configs"
    assert (configs / "config_mcu_a.txt").exists()
    assert (configs / "config_mcu_b.txt").exists()

    config_a = (configs / "config_mcu_a.txt").read_text(encoding="utf-8")
    config_b = (configs / "config_mcu_b.txt").read_text(encoding="utf-8")
    assert '"Name": "stepper_x"' in config_a
    assert '"Name": "stepper_y"' not in config_a
    assert '"Name": "stepper_y"' in config_b
    assert '"Name": "stepper_x"' not in config_b

    # Both sidecars are reported back to the caller too.
    assert "dual_board/configs/config_mcu_a.txt" in result.files
    assert "dual_board/configs/config_mcu_b.txt" in result.files


def test_generate_writes_no_sidecars_when_the_machine_does_not_compile(isolated_roots):
    """The fallback path must not leave a stale/half-assembled sidecar
    behind — no real assembly happened, so no files should exist."""
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import generate_machine_templates

    generate_machine_templates(
        "my_machine.cfg",
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
    )
    configs = isolated_roots["machines"] / "my_machine" / "configs"
    assert not any(p.name.startswith("config_") for p in configs.iterdir())


def test_generate_overwrites_hand_edited_webgui_connections_on_confirmed_override(
    isolated_roots,
):
    """webgui_connections.hal is no longer spared on a regenerate —
    once the operator confirms the "replace this machine" warning,
    every file is replaced, hand-wiring included. The one thing that
    actually blocks an accidental override is
    ``MainMachineProtectedError`` (see the tests below), not a
    selective per-file preserve."""
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import generate_machine_templates

    kwargs = dict(
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
    )
    generate_machine_templates("my_machine.cfg", **kwargs)

    configs = isolated_roots["machines"] / "my_machine" / "configs"
    hand_wiring = "# hand-wired VFD net lines\nnet spindle-cmd => vfdmod.speed\n"
    (configs / "webgui_connections.hal").write_text(hand_wiring, encoding="utf-8")

    generate_machine_templates("my_machine.cfg", confirm_override=True, **kwargs)

    text = (configs / "webgui_connections.hal").read_text(encoding="utf-8")
    assert text != hand_wiring
    assert "webgui_connections.hal - wire the" in text
    # Everything else really was regenerated too (sanity check the
    # swap isn't a no-op skip of the whole directory).
    assert "MACHINE = my_machine" in (configs / "machine.ini").read_text(encoding="utf-8")


def test_generate_refuses_to_override_the_protected_main_machine(isolated_roots):
    """The currently-selected "main" machine can't be regenerated via
    this endpoint at all — confirm_override or not. This is the real
    accident guard: clicking through a generic "replace?" warning
    must never be able to touch the machine LinuxCNC would start
    next."""
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import (
        MainMachineProtectedError,
        generate_machine_templates,
    )

    kwargs = dict(
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
    )
    generate_machine_templates("my_machine.cfg", **kwargs)

    with pytest.raises(MainMachineProtectedError):
        generate_machine_templates(
            "my_machine.cfg",
            confirm_override=True,
            protected_machine="my_machine",
            **kwargs,
        )

    # Untouched — not even the confirm_override write happened.
    configs = isolated_roots["machines"] / "my_machine" / "configs"
    assert (configs / "webgui_connections.hal").exists()


def test_protected_machine_only_blocks_when_the_folder_actually_exists(isolated_roots):
    """A stale ``default_machine.json`` pointer (the operator deleted
    the folder by hand, exactly as the error message tells them to)
    must not permanently lock out that name — first generation under
    a protected name is a fresh folder, not an override."""
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import generate_machine_templates

    kwargs = dict(
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
    )
    generate_machine_templates("my_machine.cfg", protected_machine="my_machine", **kwargs)

    configs = isolated_roots["machines"] / "my_machine" / "configs"
    assert (configs / "machine.cfg").exists()


def test_protected_machine_check_respects_target_folder(isolated_roots):
    """The protected name is ``target_folder/machine_name`` — a
    protected bare name must not accidentally block a same-named
    machine nested under a target folder, or vice versa."""
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import generate_machine_templates

    kwargs = dict(
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
    )
    # Protected name is "group/my_machine" — the bare-root generate
    # below is a different target and must proceed normally.
    generate_machine_templates(
        "my_machine.cfg", protected_machine="group/my_machine", **kwargs
    )
    configs = isolated_roots["machines"] / "my_machine" / "configs"
    assert (configs / "machine.cfg").exists()


def test_generate_seeds_webgui_connections_with_real_spindle_and_heater_bindings(
    isolated_roots,
):
    """First generation of a machine with a spindle + a heater gets a
    working `webgui_connections.hal`, not just the static header — and
    a regenerate must still preserve whatever the operator did to it
    afterward (the existing preserve-on-regenerate test covers that
    half; this one is about what gets seeded in the first place)."""
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import generate_machine_templates

    profile = (
        "[mcu]\nconnection: remora-spi\n\n"
        "[stepper_x]\nstep_pin: PF13\ndir_pin: PF12\nrotation_distance: 40\nposition_max: 300\n\n"
        "[heater_bed]\n"
        "heater_pin: PB7\nsensor_pin: PA0\nsensor_type: Generic 3950\n"
        "control: pid\npid_Kp: 20\npid_Ki: 1.5\npid_Kd: 5\nmin_temp: 0\nmax_temp: 130\n\n"
        "[mcu vfd0]\nconnection: vfd_rs485\n\n"
        "[spindle]\n"
        "run_pin: vfd0:run-forward\nspeed_pin: vfd0:rpm-in\n"
        "is_connected_pin: vfd0:is-connected\nmax_rpm: 24000\nmin_rpm: 5000\n"
    )
    (isolated_roots["profiles"] / "printer.cfg").write_text(profile, encoding="utf-8")

    generate_machine_templates(
        "printer.cfg",
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
    )

    text = (isolated_roots["machines"] / "printer" / "configs" / "webgui_connections.hal").read_text(
        encoding="utf-8"
    )
    assert "# Spindle: spindle_digital" in text
    assert "net spindle-speed-cmd => webgui.TargetRpm" in text
    assert "net spindle_digital-is-connected => webgui.is-connected" in text
    assert "# Heater: heater_bed" in text
    assert "net heater_bed-SP <= webgui.target-temperature_bed" in text
    assert "net bed-PV => webgui.bed" in text
    # The old static header text is still there too — this is a seed,
    # not a replacement of the operator-facing framing.
    assert "custom.hal always sources this file" in text


def test_generate_multi_motor_axis_emits_one_joint_per_motor(isolated_roots):
    """A dual-motor axis (``[stepper_y]`` + ``[stepper_y1]``) must
    render as one AXIS_Y with two [JOINT_N] blocks — not as two
    separate (bogus) axes — in both hardware.json and machine.ini."""
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import generate_machine_templates

    (isolated_roots["profiles"] / "gantry.cfg").write_text(
        "[stepper_x]\nstep_pin: PA0\ndir_pin: PA1\nposition_max: 300\n\n"
        "[stepper_y]\nstep_pin: PA2\ndir_pin: PA3\nposition_max: 400\n\n"
        "[stepper_y1]\nstep_pin: PA4\ndir_pin: PA5\nposition_max: 400\n\n"
        "[stepper_z]\nstep_pin: PA6\ndir_pin: PA7\nposition_max: 100\n",
        encoding="utf-8",
    )

    result = generate_machine_templates(
        "gantry.cfg",
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
    )

    configs = isolated_roots["machines"] / result.machine / "configs"

    import json

    payload = json.loads((configs / "hardware.json").read_text(encoding="utf-8"))
    axes_by_id = {a["id"]: a for a in payload["axes"]}
    assert sorted(axes_by_id) == ["x", "y", "z"]  # "y1" is NOT its own axis
    assert len(axes_by_id["y"]["joint_numbers"]) == 2
    joint_ids = {j["id"] for j in payload["joints"]}
    assert {"stepper_y", "stepper_y1"} <= joint_ids

    ini = (configs / "machine.ini").read_text(encoding="utf-8")
    assert "[AXIS_Y]" in ini
    assert "[AXIS_Y1]" not in ini
    assert "coordinates=XYYZ" in ini
    assert "JOINTS = 4" in ini


def test_generate_existing_machine_raises_without_confirm(isolated_roots):
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import MachineExistsError, generate_machine_templates

    kwargs = dict(
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
        catalog=None,
    )
    generate_machine_templates("my_machine.cfg", **kwargs)

    from services.machinetemplates import GENERATED_FILES

    with pytest.raises(MachineExistsError) as excinfo:
        generate_machine_templates("my_machine.cfg", **kwargs)
    assert excinfo.value.machine == "my_machine"
    assert len(excinfo.value.existing_files) == len(GENERATED_FILES)

    # confirm_override replaces the set (still the full artifact set).
    result = generate_machine_templates("my_machine.cfg", confirm_override=True, **kwargs)
    assert len(result.files) == len(GENERATED_FILES)


def test_generate_into_nested_target_folder(isolated_roots):
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import generate_machine_templates

    result = generate_machine_templates(
        "my_machine.cfg",
        target_folder="workshop/mills",
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
        catalog=None,
    )
    assert result.target_folder == "workshop/mills"
    assert (isolated_roots["machines"] / "workshop" / "mills" / "my_machine" / "configs" / "machine.hal").exists()

    # A second machine of the same name in a different folder is fine.
    result2 = generate_machine_templates(
        "my_machine.cfg",
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
        catalog=None,
    )
    assert result2.files[0].startswith("my_machine/")


def test_generate_rejects_bad_paths(isolated_roots):
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import generate_machine_templates

    kwargs = dict(
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
        catalog=None,
    )
    with pytest.raises(FileNotFoundError):
        generate_machine_templates("missing.cfg", **kwargs)
    with pytest.raises(ValueError):
        generate_machine_templates("../escape.cfg", **kwargs)
    with pytest.raises(ValueError):
        generate_machine_templates("my_machine.cfg", target_folder="../up", **kwargs)


# ---------------------------------------------------------------------- #
# Router surface                                                          #
# ---------------------------------------------------------------------- #

def test_machines_tree_and_generate_roundtrip(machine_app, isolated_roots):
    client = TestClient(machine_app)

    resp = client.get("/api/v1/modules/machineconfig/machines/tree")
    assert resp.status_code == 200
    assert resp.json()["root"] == "machines"
    assert resp.json()["entries"] == []

    resp = client.post(
        "/api/v1/modules/machineconfig/machines/generate",
        json={"profile_path": "my_machine.cfg"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["machine"] == "my_machine"
    from services.machinetemplates import GENERATED_FILES

    assert sorted(f["name"] for f in body["files"]) == sorted(GENERATED_FILES)

    resp = client.get("/api/v1/modules/machineconfig/machines/tree")
    paths = [e["path"] for e in resp.json()["entries"]]
    assert "my_machine" in paths
    assert "my_machine/configs/machine.hal" in paths
    # Template files are editable (not read-only).
    hal_entry = next(e for e in resp.json()["entries"] if e["path"] == "my_machine/configs/machine.hal")
    assert hal_entry["read_only"] is False


def test_generate_machine_exists_conflict_flow(machine_app, isolated_roots):
    client = TestClient(machine_app)
    payload = {"profile_path": "my_machine.cfg"}

    first = client.post("/api/v1/modules/machineconfig/machines/generate", json=payload)
    assert first.status_code == 200

    conflict = client.post("/api/v1/modules/machineconfig/machines/generate", json=payload)
    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert detail["kind"] == "machine_exists"
    assert detail["machine"] == "my_machine"
    from services.machinetemplates import GENERATED_FILES

    assert len(detail["existing"]) == len(GENERATED_FILES)

    override = client.post(
        "/api/v1/modules/machineconfig/machines/generate",
        json={**payload, "confirm_override": True},
    )
    assert override.status_code == 200


def test_generate_main_machine_conflict_flow(machine_app, isolated_roots, monkeypatch):
    """The router asks ``MachineLifecycleService`` which machine is
    currently "main" and refuses to regenerate it — a 403, not the
    409 override-confirm flow, since there is no confirm_override
    that makes this request succeed."""
    import routers.machineconfig as router_module

    client = TestClient(machine_app)
    payload = {"profile_path": "my_machine.cfg"}

    first = client.post("/api/v1/modules/machineconfig/machines/generate", json=payload)
    assert first.status_code == 200

    monkeypatch.setattr(
        router_module,
        "get_machine_lifecycle_service",
        lambda: type("_Stub", (), {"default_machine": staticmethod(lambda: "my_machine")})(),
    )

    protected = client.post(
        "/api/v1/modules/machineconfig/machines/generate",
        json={**payload, "confirm_override": True},
    )
    assert protected.status_code == 403
    detail = protected.json()["detail"]
    assert detail["kind"] == "main_machine_protected"
    assert detail["machine"] == "my_machine"


def test_generate_missing_profile_returns_404(machine_app, isolated_roots):
    client = TestClient(machine_app)
    resp = client.post(
        "/api/v1/modules/machineconfig/machines/generate",
        json={"profile_path": "nope.cfg"},
    )
    assert resp.status_code == 404


def test_generate_profile_escape_returns_400(machine_app, isolated_roots):
    client = TestClient(machine_app)
    resp = client.post(
        "/api/v1/modules/machineconfig/machines/generate",
        json={"profile_path": "../escape.cfg"},
    )
    assert resp.status_code == 400


def test_machines_crud_roundtrip(machine_app, isolated_roots):
    client = TestClient(machine_app)
    base = "/api/v1/modules/machineconfig/machines"

    resp = client.post(f"{base}/folder", json={"path": "notes"})
    assert resp.status_code == 200
    resp = client.post(f"{base}/file", json={"path": "notes/readme.txt"})
    assert resp.status_code == 200
    resp = client.put(f"{base}/content", params={"path": "notes/readme.txt"}, json={"content": "hello"})
    assert resp.status_code == 200
    resp = client.get(f"{base}/content", params={"path": "notes/readme.txt"})
    assert resp.status_code == 200
    assert resp.json()["content"] == "hello"
    resp = client.put(f"{base}/rename", json={"source": "notes/readme.txt", "destination": "notes/done.txt"})
    assert resp.status_code == 200
    resp = client.delete(f"{base}/entry", params={"path": "notes/done.txt"})
    assert resp.status_code == 200
    resp = client.delete(f"{base}/entry", params={"path": "notes"})
    assert resp.status_code == 200

    # Non-empty folder deletion surfaces 400.
    client.post(f"{base}/folder", json={"path": "busy"})
    client.post(f"{base}/file", json={"path": "busy/child.cfg"})
    resp = client.delete(f"{base}/entry", params={"path": "busy"})
    assert resp.status_code == 400
