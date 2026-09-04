"""Tests for the machine template generator (compiler replacement).

Covers:

* ``build_pin_catalog`` introspection of the frozen pin-container
  dataclasses (readonly / readwrite / static / unconnected / nested).
* ``render_ini_template`` / ``render_hal_template`` output contracts.
* ``generate_machine_templates``: artifact set, machine-exists guard,
  confirm_override, nested target folders, path-safety.
* The ``/machines/*`` router surface (tree, generate + 409 flow, CRUD).
* The ``deprecated`` flag on the compiler registry listing.
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


def test_render_ini_template_skeleton():
    from services.machinetemplates import render_ini_template

    payload = {"axes": [{"id": "x", "joint_numbers": [0]}], "joints": [{"id": "stepper_x", "joint_number": 0}]}
    text = render_ini_template("my_machine", payload)

    assert "MACHINE = my_machine" in text
    assert "# [AXIS_X]" in text
    assert "# [JOINT_0]" in text
    assert "# [HAL]" in text
    # Only the EMC section is live.
    live_sections = [
        l for l in text.splitlines() if l.startswith("[")
    ]
    assert live_sections == ["[EMC]"]


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


def test_generate_existing_machine_raises_without_confirm(isolated_roots):
    from domain_file_services import ConfigFileService, MachineFileService
    from services.machinetemplates import MachineExistsError, generate_machine_templates

    kwargs = dict(
        config_service=ConfigFileService(root=isolated_roots["profiles"]),
        machine_service=MachineFileService(root=isolated_roots["machines"]),
        catalog=None,
    )
    generate_machine_templates("my_machine.cfg", **kwargs)

    with pytest.raises(MachineExistsError) as excinfo:
        generate_machine_templates("my_machine.cfg", **kwargs)
    assert excinfo.value.machine == "my_machine"
    assert len(excinfo.value.existing_files) == 4

    # confirm_override replaces the set (still exactly 4 files).
    result = generate_machine_templates("my_machine.cfg", confirm_override=True, **kwargs)
    assert len(result.files) == 4


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
    assert sorted(f["name"] for f in body["files"]) == [
        "hardware.json",
        "machine.cfg",
        "machine.hal",
        "machine.ini",
    ]

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
    assert len(detail["existing"]) == 4

    override = client.post(
        "/api/v1/modules/machineconfig/machines/generate",
        json={**payload, "confirm_override": True},
    )
    assert override.status_code == 200


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


def test_compilers_listing_marks_klipper_deprecated(machine_app, isolated_roots):
    client = TestClient(machine_app)
    resp = client.get("/api/v1/modules/machineconfig/compilers")
    assert resp.status_code == 200
    compilers = resp.json()["compilers"]
    entry = next(c for c in compilers if c["id"] == "klipper-to-linuxcnc")
    assert entry["deprecated"] is True
