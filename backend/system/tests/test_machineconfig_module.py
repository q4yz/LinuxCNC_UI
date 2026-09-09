"""Tests for the machineconfig backend module.

Covers:

* Boot-time discovery + router mounting under
  ``/api/v1/modules/machineconfig``.
* The profiles CRUD endpoints support list/read/create/rename/delete
  on a per-test isolated ``profiles/`` tree (we monkeypatch the
  constants for the duration of each test).
* ``hardware.json`` v2 payload shape, built directly via
  :func:`build_hardware_json` (independent of any HTTP endpoint).
* The structured ``ConfigValidationError`` envelope surfaces through
  ``POST /machines/generate`` the same way it used to through the
  now-removed ``POST /compile``.

The pluggable ``Compiler`` framework (``GET /compilers``,
``POST /compile``, ``GET /staged`` + content, Remora
``config.txt``) was removed, and so was the later ``active/`` deploy
step (``GET /active`` + content, ``POST /deploy``,
``GET /machine-name``) — a machine's config now lives directly under
``machine_config/machines/<name>/`` and is addressed by name; see
``MachineLifecycleService`` and ``HardwareConfigService``.
"""

from __future__ import annotations
from tests._module_app_factory import build_module_app

import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus

# ---------------------------------------------------------------------- #
# Fixtures                                                                #
# ---------------------------------------------------------------------- #

@pytest.fixture()
def isolated_machine_config(monkeypatch, tmp_path):
    """Re-point every machineconfig service at a fresh ``tmp_path`` tree.

    The test never touches the real ``machine_config/`` directory;
    we give each test a fresh profiles / machines subtree so the CRUD
    assertions are deterministic.

    The FileService layer keeps the canonical roots in
    :mod:`domain_file_services`. The fixture rewrites those
    module-level constants and resets the cached services so each
    test gets fresh instances bound to the isolated tree.
    """
    mc = tmp_path / "machine_config"
    profiles = mc / "profiles"
    machines = mc / "machines"
    for d in (profiles, machines):
        d.mkdir(parents=True, exist_ok=True)

    from services import domain_file_services, reset_service_cache

    paths_mod = domain_file_services.paths
    monkeypatch.setattr(paths_mod, "MACHINE_CONFIG_DIR", mc)
    monkeypatch.setattr(paths_mod, "PROFILES_DIR", profiles)
    monkeypatch.setattr(paths_mod, "MACHINES_DIR", machines)
    # Drop the service-instance cache so the next ``get_*_service``
    # call picks up the freshly-monkeypatched roots.
    reset_service_cache()

    # Seed a starter profile that contains the ``#Start`` marker so
    # the "ready" badge has something to flag.
    (profiles / "starter.cfg").write_text(
        "#Start\n[printer]\nkinematics: cartesian\nmax_velocity: 250.0\n"
        "[stepper_x]\n    step_pin: PC2\n    dir_pin: PB9\n    enable_pin: !PC3\n"
    )

    yield {
        "machine_config": mc,
        "profiles": profiles,
        "machines": machines,
    }

    # Make sure a follow-up test (in the same process) starts from a
    # clean service cache instead of inheriting the isolated roots.
    reset_service_cache()

def _machineconfig_app(tmp_data_root, clean_env=None):
    """Build a FastAPI app with the machineconfig module wired up.

    Registers the structured ``ConfigValidationError`` handler that
    the module's ``on_load`` installed on the FastAPI app —
    ``POST /machines/generate`` raises that exception (via the
    shared parser) and the handler turns it into a ``400`` with the
    operator-facing envelope.
    """
    from routers.machineconfig import register_exception_handlers

    app = build_module_app("machineconfig", tmp_data_root)
    register_exception_handlers(app)
    return app, None

def _generate(client: TestClient, profile_path: str = "starter.cfg", **kwargs):
    return client.post(
        "/api/v1/modules/machineconfig/machines/generate",
        json={"profile_path": profile_path, **kwargs},
    )

# ---------------------------------------------------------------------- #
# Boot / lifecycle                                                        #
# ---------------------------------------------------------------------- #

def test_machineconfig_endpoints_are_mounted(
    tmp_data_root, clean_env, isolated_machine_config
):
    """The router mounts under ``/api/v1/modules/machineconfig`` and the
    canonical settings endpoint is reachable (no operator-tunable
    knobs today — see ``MachineConfigSettings``)."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)

    resp = client.get("/api/v1/modules/machineconfig/settings")
    assert resp.status_code == 200
    assert resp.json() == {}

# ---------------------------------------------------------------------- #
# Profiles CRUD                                                           #
# ---------------------------------------------------------------------- #

def test_profiles_tree_lists_seeded_file(
    tmp_data_root, clean_env, isolated_machine_config
):
    """``GET /profiles/tree`` returns every entry plus the marker flag."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)

    resp = client.get("/api/v1/modules/machineconfig/profiles/tree")
    assert resp.status_code == 200
    body = resp.json()
    assert body["root"] == "profiles"
    names = [e["name"] for e in body["entries"]]
    assert "starter.cfg" in names

    starter = next(e for e in body["entries"] if e["name"] == "starter.cfg")
    assert starter["kind"] == "file"
    assert starter["has_marker"] is True

def test_profiles_create_folder_file_read_write_rename_delete(
    tmp_data_root, clean_env, isolated_machine_config
):
    """The full CRUD round-trip works on the profiles/ tree."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)

    # Create a folder.
    resp = client.post(
        "/api/v1/modules/machineconfig/profiles/folder",
        json={"path": "subdir"},
    )
    assert resp.status_code == 200

    # Create a file inside the new folder.
    resp = client.post(
        "/api/v1/modules/machineconfig/profiles/file",
        json={"path": "subdir/new.cfg"},
    )
    assert resp.status_code == 200

    # Write content to the new file.
    resp = client.put(
        "/api/v1/modules/machineconfig/profiles/content",
        params={"path": "subdir/new.cfg"},
        json={"content": "#Start\n[printer]\nkinematics: cartesian\n"},
    )
    assert resp.status_code == 200

    # Read it back.
    resp = client.get(
        "/api/v1/modules/machineconfig/profiles/content",
        params={"path": "subdir/new.cfg"},
    )
    assert resp.status_code == 200
    assert "kinematics: cartesian" in resp.json()["content"]

    # Rename the file.
    resp = client.put(
        "/api/v1/modules/machineconfig/profiles/rename",
        json={"source": "subdir/new.cfg", "destination": "subdir/renamed.cfg"},
    )
    assert resp.status_code == 200

    # Delete the renamed file (folder is then empty and can be removed too).
    resp = client.delete(
        "/api/v1/modules/machineconfig/profiles/entry",
        params={"path": "subdir/renamed.cfg"},
    )
    assert resp.status_code == 200
    resp = client.delete(
        "/api/v1/modules/machineconfig/profiles/entry",
        params={"path": "subdir"},
    )
    assert resp.status_code == 200

def test_profiles_delete_non_empty_folder_returns_400(
    tmp_data_root, clean_env, isolated_machine_config
):
    """Deleting a folder that still has children fails fast."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    client.post(
        "/api/v1/modules/machineconfig/profiles/folder",
        json={"path": "nonempty"},
    )
    client.post(
        "/api/v1/modules/machineconfig/profiles/file",
        json={"path": "nonempty/child.cfg"},
    )
    resp = client.delete(
        "/api/v1/modules/machineconfig/profiles/entry",
        params={"path": "nonempty"},
    )
    assert resp.status_code == 400

def test_profiles_create_existing_returns_409(
    tmp_data_root, clean_env, isolated_machine_config
):
    """``POST /profiles/folder`` rejects duplicate names."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    client.post(
        "/api/v1/modules/machineconfig/profiles/folder",
        json={"path": "dup"},
    )
    resp = client.post(
        "/api/v1/modules/machineconfig/profiles/folder",
        json={"path": "dup"},
    )
    assert resp.status_code == 409

def test_profiles_outside_root_rejected(
    tmp_data_root, clean_env, isolated_machine_config
):
    """A relative path that escapes ``profiles/`` is rejected with 400.

    ``httpx`` (used by :class:`TestClient`) normalises ``..`` segments in
    the URL before they reach FastAPI's router, so we exercise the
    escape through a body payload (``profile_path``) instead — that's
    the path ``/machines/generate`` joins onto the profiles root.
    """
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    resp = _generate(client, profile_path="../escape.cfg")
    assert resp.status_code == 400

# ---------------------------------------------------------------------- #
# hardware.json v2 payload (issue: dynamic heater hardware.json)          #
# ---------------------------------------------------------------------- #

def test_hardware_json_v2_emits_user_example(
    tmp_data_root, clean_env
):
    """The user's example ([extruder] + [heater_bed]) compiles into the
    hardware.json v2 shape with two heaters, two temperature sensors,
    two axes, and three endstop records per Klipper switch.

    The end-to-end assertion ties the parser, the v2 generator,
    and the strict Pydantic model together.
    """
    from services.machineconfig.hardware_json_generator import (
        build_hardware_json,
    )
    from machineconfig_parser import MachineConfigParser

    config = """
[stepper_x]
step_pin: PF13
dir_pin: PF12
enable_pin: !PF14
microsteps: 16
rotation_distance: 40.0
position_endstop: 0.0
position_max: 300.0

[stepper_y]
step_pin: PG0
dir_pin: PG1
enable_pin: !PF15
microsteps: 16
rotation_distance: 40.0
position_endstop: 0.0
position_max: 300.0

[stepper_z]
step_pin: PG2
dir_pin: PG3
enable_pin: !PF16
microsteps: 16
rotation_distance: 40.0
position_endstop: 0.0
position_max: 300.0

[endstop_switch x_min]
stepper: x
pin: ^PC0

[endstop_switch y_min]
stepper: y
pin: ^PC1

[endstop_switch z_min]
stepper: z
pin: ^PC2

[extruder]
step_pin: PC9
dir_pin: PC8
enable_pin: !PD1
microsteps: 16
rotation_distance: 33.500
heater_pin: PE3
sensor_type: EPCOS 100K B57560G104F
sensor_pin: PA1
control: pid
pid_Kp: 22.2
pid_Ki: 1.08
pid_Kd: 114
min_temp: 0
max_temp: 250

[heater_bed]
heater_pin: PB7
sensor_type: Generic 3950
sensor_pin: PA0
control: watermark
min_temp: 0
max_temp: 130
"""
    graph = MachineConfigParser().parse_string(config)
    payload = build_hardware_json(graph, "test")

    # Top-level shape. 2.2 added the losslessness fields (PID gains,
    # motion envelope, driver settings); 2.1 files still validate.
    assert payload["version"] == "2.2"
    assert payload["machine"] == "test"
    assert payload["hal_type"] == "remora"

    # Four axes — X / Y / Z Cartesian + the extruder (axis ``A``).
    # Phase 7 extended the AxisBuilder so the extruder becomes its
    # own axis instead of staying under the heaters list only.
    # Axes carry a string ``id`` (canonical LinuxCNC letter) plus
    # ``joint_numbers`` listing every driving joint.
    assert [a["id"] for a in payload["axes"]] == ["x", "y", "z", "a"]

    # Three joints from the Klipper stepper sections plus the
    # synthesised extruder joint (canonical numbering: X, Y, Z,
    # then extruders).
    joint_ids = [s["id"] for s in payload["joints"]]
    assert joint_ids == [
        "stepper_x",
        "stepper_y",
        "stepper_z",
        "heater_extruder",
    ]
    assert [s["joint_number"] for s in payload["joints"]] == [0, 1, 2, 3]

    # Three drivers, one per Cartesian stepper. The synthesised
    # extruder joint has no driver (drivers[] is motor-driver only).
    assert [d["id"] for d in payload["drivers"]] == [
        "driver_stepper_x",
        "driver_stepper_y",
        "driver_stepper_z",
    ]

    # Three endstop records — one per Klipper switch. Each carries
    # only ``{id, pin}``; behaviour tags were dropped when the schema
    # was slimmed to mirror the Klipper source shape.
    endstop_records = payload["endstops"]
    assert len(endstop_records) == 3
    endstop_ids = {r["id"] for r in endstop_records}
    assert endstop_ids == {"endstop_x_min", "endstop_y_min", "endstop_z_min"}
    for record in endstop_records:
        assert set(record.keys()) == {"id", "pin"}

    # Each Cartesian axis references its endstop by id and carries
    # its ``position_endstop``; the extruder (A) axis is endstop-less.
    axes_by_id = {a["id"]: a for a in payload["axes"]}
    assert axes_by_id["x"]["endstop"] == "endstop_x_min"
    assert axes_by_id["y"]["endstop"] == "endstop_y_min"
    assert axes_by_id["z"]["endstop"] == "endstop_z_min"
    assert axes_by_id["a"].get("endstop") is None
    assert axes_by_id["a"].get("endstop_pin") is None
    # The extruder (A) axis owns the synthesised extruder joint.
    assert axes_by_id["a"]["joint_numbers"] == [3]
    assert axes_by_id["x"]["joint_numbers"] == [0]
    assert axes_by_id["y"]["joint_numbers"] == [1]
    assert axes_by_id["z"]["joint_numbers"] == [2]
    assert axes_by_id["x"]["position_endstop"] == 0.0
    assert axes_by_id["y"]["position_endstop"] == 0.0
    assert axes_by_id["z"]["position_endstop"] == 0.0
    assert axes_by_id["x"]["position_max"] == 300.0
    assert axes_by_id["y"]["position_max"] == 300.0
    assert axes_by_id["z"]["position_max"] == 300.0
    # The old ``endstops`` array on each axis is gone.
    for axis in payload["axes"]:
        assert "endstops" not in axis
    # The old ``pos`` field on each axis is gone (renamed to
    # ``position_endstop``).
    for axis in payload["axes"]:
        assert "pos" not in axis

    # Two tools (extruder + heated_bed), two temperature sensors.
    assert [t["id"] for t in payload["tools"]] == ["heater_extruder", "heater_bed"]
    assert [t["type"] for t in payload["tools"]] == ["extruder", "heated_bed"]
    assert [s["id"] for s in payload["temperature_sensors"]] == ["extruder", "bed"]
    # Tool.sensor references resolve into temperature_sensors[].id.
    tool_sensor_refs = {t["id"]: t["sensor"] for t in payload["tools"]}
    assert tool_sensor_refs == {
        "heater_extruder": "extruder",
        "heater_bed": "bed",
    }

def test_hardware_json_v2_empty_arrays_when_no_heaters(
    tmp_data_root, clean_env
):
    """A profile with no heater sections compiles to empty
    ``tools`` / ``temperature_sensors`` / ``fans`` lists."""
    from services.machineconfig.hardware_json_generator import (
        build_hardware_json,
    )
    from machineconfig_parser import MachineConfigParser

    config = """
[printer]
kinematics: cartesian

[stepper_x]
step_pin: PF13
"""
    graph = MachineConfigParser().parse_string(config)
    payload = build_hardware_json(graph, "no-heaters")
    assert payload["tools"] == []
    assert payload["temperature_sensors"] == []
    assert payload["fans"] == []
    assert payload["endstops"] == []

# ---------------------------------------------------------------------- #
# Structured-error response (issue #99)                                   #
# ---------------------------------------------------------------------- #

def test_generate_duplicate_stepper_pin_returns_structured_error(
    tmp_data_root, clean_env, isolated_machine_config
):
    """``POST /machines/generate`` on the issue's example config returns
    the structured error envelope.

    The user's example config (see issue #99) declares ``[stepper_x]``,
    ``[stepper_y]``, ``[stepper_z]`` that all share pins ``PG0``,
    ``PG1``, and ``!PF15``. The parser rejects this with
    :class:`DuplicateStepperPinError`; the FastAPI exception handler
    converts that into the documented JSON shape::

        {"error": {"section", "key", "line", "message", "kind"}}

    This is the single contract the frontend toast channel depends on.
    """
    profiles = isolated_machine_config["profiles"]
    (profiles / "duplicate_pins.cfg").write_text(
        "#Start\n"
        "[stepper_x]\nstep_pin: PG0\ndir_pin: PG1\nenable_pin: !PF15\n\n"
        "[stepper_y]\nstep_pin: PG0\ndir_pin: PG1\nenable_pin: !PF15\n\n"
        "[stepper_z]\nstep_pin: PG0\ndir_pin: PG1\nenable_pin: !PF15\n\n"
        "[extruder]\nstep_pin: PA4\ndir_pin: PA5\nheater_pin: PE3\nsensor_pin: PA1\ncontrol: pid\npid_Kp: 1.0\npid_Ki: 1.0\npid_Kd: 1.0\nmin_temp: 0\nmax_temp: 250\n\n"
        "[heater_bed]\nheater_pin: PB0\nsensor_pin: PB1\ncontrol: watermark\nmin_temp: 0\nmax_temp: 130\n",
        encoding="utf-8",
    )

    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    resp = _generate(client, profile_path="duplicate_pins.cfg")

    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert "error" in body, "generate must surface the structured envelope"
    error = body["error"]
    # Every documented field is present. ``line`` may be ``None`` —
    # configparser does not expose source-line offsets in this
    # version, and the schema keeps the slot reserved.
    for field_name in ("section", "key", "line", "message", "kind"):
        assert field_name in error, f"missing field: {field_name}"
    assert error["kind"] == "duplicate_stepper_pin"
    assert error["key"] in {"step_pin", "dir_pin", "enable_pin", "endstop_pin"}
    assert error["section"] in {"x", "y", "z"}
    assert (
        "PG0" in error["message"]
        or "PG1" in error["message"]
        or "!PF15" in error["message"]
    )


def test_generate_malformed_syntax_returns_structured_error(
    tmp_data_root, clean_env, isolated_machine_config
):
    """A profile that violates INI syntax itself still returns the
    structured envelope, not a raw 500.

    Raw ``configparser.Error`` subclasses (duplicate key, line with
    no ``key: value`` separator) are not ``ValueError`` s, so before
    the :class:`MalformedConfigError` wrapping they escaped every
    handler and crashed the ASGI app. This is the HTTP-level guard
    for that regression.
    """
    profiles = isolated_machine_config["profiles"]
    (profiles / "malformed.cfg").write_text(
        "#Start\n[stepper_x]\nstep_pin: PF13\ndir_pin: PF12\nstep_pin: PF14\n",
        encoding="utf-8",
    )

    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    resp = _generate(client, profile_path="malformed.cfg")

    assert resp.status_code == 400, resp.text
    error = resp.json()["error"]
    assert error["kind"] == "malformed_config"
    assert error["section"] == "stepper_x"
    assert error["key"] == "step_pin"
    assert "already exists" in error["message"]
