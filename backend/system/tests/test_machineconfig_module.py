"""Tests for the machineconfig backend module (issue #41).

Covers:

* Boot-time discovery + router mounting under
  ``/api/v1/modules/machineconfig``.
* The default compiler is registered (Kl ipperToLinuxCNCCompiler).
* ``POST /compile`` clears ``ready_for_deploy/``, stages the four
  canonical artifacts, and returns the staged listing.
* ``GET /staged`` + ``GET /staged/content/{name}`` surface the
  read-only view.
* ``POST /deploy`` requires ``confirm_flash=true`` when the module
  setting is on, copies artifacts into ``active/``, and refreshes the
  machine-name probe.
* ``GET /active`` + ``GET /active/content/{name}`` mirror the staged
  read-only endpoints.
* The profiles CRUD endpoints support list/read/create/rename/delete
  on a per-test isolated ``profiles/`` tree (we monkeypatch the
  constants for the duration of each test).
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
    we give each test a fresh profiles / staged / active subtree so
    the CRUD assertions are deterministic.

    The new FileService layer keeps the canonical roots in
    :mod:`services.domain_file_services`. The fixture rewrites those
    module-level constants and resets the cached services so each
    test gets fresh instances bound to the isolated tree.
    """
    mc = tmp_path / "machine_config"
    profiles = mc / "profiles"
    staged = mc / "ready_for_deploy"
    active = mc / "active"
    for d in (profiles, staged, active):
        d.mkdir(parents=True, exist_ok=True)

    from services import domain_file_services, reset_service_cache

    # The services resolve their roots lazily through the shared
    # ``paths`` module (see ``domain_file_services/paths.py``), so
    # re-pointing those module attributes + dropping the service
    # cache fully isolates every machineconfig endpoint.
    paths_mod = domain_file_services.paths
    monkeypatch.setattr(paths_mod, "MACHINE_CONFIG_DIR", mc)
    monkeypatch.setattr(paths_mod, "PROFILES_DIR", profiles)
    monkeypatch.setattr(paths_mod, "MACHINES_DIR", mc / "machines")
    monkeypatch.setattr(paths_mod, "STAGED_DIR", staged)
    monkeypatch.setattr(paths_mod, "ACTIVE_DIR", active)
    # Drop the service-instance cache so the next ``get_*_service``
    # call picks up the freshly-monkeypatched roots.
    reset_service_cache()

    # Seed a starter profile that contains the ``#Start`` marker so
    # the inline compile action has something to point at. An empty
    # ``[mcu]`` defaults to ``remora-spi + BIGTREETECH OCTOPUS`` so
    # the compiler emits the full artifact set (including the Remora
    # ``config.txt`` payload).
    (profiles / "starter.cfg").write_text(
        "#Start\n[mcu]\n[printer]\nkinematics: cartesian\nmax_velocity: 250.0\n"
        "[stepper_x]\n    step_pin: PC2\n    dir_pin: PB9\n    enable_pin: !PC3\n"
    )

    yield {
        "machine_config": mc,
        "profiles": profiles,
        "staged": staged,
        "active": active,
    }

    # Make sure a follow-up test (in the same process) starts from a
    # clean service cache instead of inheriting the isolated roots.
    reset_service_cache()

def _machineconfig_app(tmp_data_root, clean_env=None):
    """Build a FastAPI app with the machineconfig module wired up.

    Registers the structured ``ConfigValidationError`` handler
    that the legacy ``MachineConfigModule.on_load`` installed on
    the FastAPI app — the router's compile endpoint raises that
    exception and the handler turns it into a ``400`` with the
    operator-facing envelope.
    """
    from routers.machineconfig import register_exception_handlers

    app = build_module_app("machineconfig", tmp_data_root)
    register_exception_handlers(app)
    return app, None

# ---------------------------------------------------------------------- #
# Boot / lifecycle                                                        #
# ---------------------------------------------------------------------- #

def test_machineconfig_endpoints_are_mounted(
    tmp_data_root, clean_env, isolated_machine_config
):
    """The router mounts under ``/api/v1/modules/machineconfig`` and the
    four canonical settings endpoints are reachable."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)

    # Compilers listing is exposed.
    resp = client.get("/api/v1/modules/machineconfig/compilers")
    assert resp.status_code == 200
    body = resp.json()
    assert "compilers" in body
    assert any(c["id"] == "klipper-to-linuxcnc" for c in body["compilers"])

    # The four canonical settings endpoints are mounted by the
    # registry with the documented defaults.
    resp = client.get("/api/v1/modules/machineconfig/settings")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["default_compiler_id"] == "klipper-to-linuxcnc"
    assert payload["require_confirm_flash"] is True
    assert payload["auto_readonly_after_stage"] is True
    assert payload["confirm_flash_default"] is False

def test_klipper_compiler_is_registered(tmp_data_root, clean_env):
    """The default compiler is registered on package import."""
    from services.machineconfig import registry

    assert "klipper-to-linuxcnc" in registry
    compiler = registry.get("klipper-to-linuxcnc")
    assert compiler.id == "klipper-to-linuxcnc"
    assert compiler.title == "Klipper → LinuxCNC"
    assert compiler.source_marker == "#Start"

def test_klipper_compiler_compiles_a_profile(tmp_data_root, clean_env):
    """The compiler produces the four canonical artifacts.

    The fifth artifact ``config.txt`` is conditional on a single
    remora MCU being declared: the profile below omits the
    ``[mcu]`` section, so the new contract skips the Remora board
    payload entirely (no stale JSON reaches the deploy step). The
    four always-on artifacts are the canonical smoke test.
    """
    from services.machineconfig import registry

    compiler = registry.get("klipper-to-linuxcnc")
    src = tmp_data_root / "printer.cfg"
    src.write_text(
        "[printer]\n"
        "kinematics: cartesian\n"
        "max_velocity: 300\n\n"
        "[stepper_x]\n"
        "step_pin: PF13\n"
    )
    out = tmp_data_root / "staged"
    out.mkdir()

    artifacts = compiler.compile(src, out)
    names = sorted(p.name for p in artifacts)
    assert names == [
        "hardware.json",
        "linuxcnc.ini",
        "machine.cfg",
        "machine.hal",
    ]
    # No remora MCU was declared → config.txt must NOT be emitted.
    assert not (out / "config.txt").exists()

    # Each artifact is non-empty and the machine.cfg is a verbatim copy.
    machine_cfg = (out / "machine.cfg").read_text()
    assert "#Start" not in machine_cfg  # our seed profile doesn't carry the marker
    assert "[stepper_x]" in machine_cfg

    ini = (out / "linuxcnc.ini").read_text()
    assert "[EMC]" in ini
    # The Remora-flavoured template uses ``MACHINE = Remora-XY`` per
    # the template spec; the legacy literal ``linuxcnc`` was retired.
    assert "MACHINE = Remora-XY" in ini

def test_klipper_compiler_has_source_marker(tmp_data_root, clean_env):
    """Marker detection returns True only for files containing ``#Start``."""
    from services.machineconfig import registry

    compiler = registry.get("klipper-to-linuxcnc")
    with_marker = tmp_data_root / "with.cfg"
    without_marker = tmp_data_root / "without.cfg"
    with_marker.write_text("#Start\n[printer]\nkinematics: cartesian\n")
    without_marker.write_text("[printer]\nkinematics: cartesian\n")

    assert compiler.has_source_marker(with_marker) is True
    assert compiler.has_source_marker(without_marker) is False

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
    the path that the compiler endpoint actually joins onto the root.
    """
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/machineconfig/compile",
        json={
            "profile_path": "../escape.cfg",
            "compiler_id": "klipper-to-linuxcnc",
        },
    )
    assert resp.status_code == 400

# ---------------------------------------------------------------------- #
# Compile / Deploy                                                        #
# ---------------------------------------------------------------------- #

def test_compile_stages_artifacts_and_lists_them(
    tmp_data_root, clean_env, isolated_machine_config
):
    """``POST /compile`` clears staged/, writes 4 artifacts, returns listing."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/modules/machineconfig/compile",
        json={"profile_path": "starter.cfg", "compiler_id": "klipper-to-linuxcnc"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["compiler"] == "klipper-to-linuxcnc"
    assert body["profile"] == "starter.cfg"
    assert sorted(body["artifacts"]) == [
        "config.txt",
        "hardware.json",
        "linuxcnc.ini",
        "machine.cfg",
        "machine.hal",
    ]
    assert len(body["staged"]) == 5

    # ``GET /staged`` mirrors the listing.
    resp = client.get("/api/v1/modules/machineconfig/staged")
    assert resp.status_code == 200
    assert len(resp.json()) == 5

def test_compile_does_not_chmod_staged_files(
    tmp_data_root, clean_env, isolated_machine_config
):
    """The compile step must leave on-disk POSIX mode bits alone.

    Pre-3.13 ``shutil.rmtree`` handled read-only descendants
    silently via a single-arg ``onerror`` callback. On Python
    3.13 the walker opens directories with
    ``os.open(O_RDONLY | O_NONBLOCK)`` first and trips on
    externally-chmod'd trees; we sidestep the whole class of
    failures by not chmod'ing in the first place.

    This test pins that contract: run compile twice and assert
    every staged entry's mode bits are unchanged between the
    two runs. (``test_staged_content_endpoint_returns_text``
    below already pins that the API surfaces ``read_only=true``
    on staged content — that assertion is unchanged after this
    change because the source-level read-only state has always
    been driven by ``StagedFileService.default_read_only=True``.)
    """
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)

    resp1 = client.post(
        "/api/v1/modules/machineconfig/compile",
        json={"profile_path": "starter.cfg", "compiler_id": "klipper-to-linuxcnc"},
    )
    assert resp1.status_code == 200, resp1.text
    staged = isolated_machine_config["staged"]
    first_modes = {
        str(entry.relative_to(staged)): entry.stat().st_mode
        for entry in [staged, *staged.rglob("*")]
    }

    resp2 = client.post(
        "/api/v1/modules/machineconfig/compile",
        json={"profile_path": "starter.cfg", "compiler_id": "klipper-to-linuxcnc"},
    )
    assert resp2.status_code == 200, resp2.text
    second_modes = {
        str(entry.relative_to(staged)): entry.stat().st_mode
        for entry in [staged, *staged.rglob("*")]
    }

    assert first_modes == second_modes, (
        f"compile must not change POSIX mode bits on the "
        f"staged tree; first={first_modes!r} second={second_modes!r}"
    )

def test_mark_read_only_is_a_noop(
    tmp_data_root, clean_env, isolated_machine_config
):
    """``StagedFileService.mark_read_only`` and
    ``FileService.set_read_only`` are documented no-ops now
    that read-only state is the ``default_read_only`` policy,
    not a POSIX mode bit.

    Pin the contract so any future revert to ``os.chmod`` is
    an explicit, opt-in decision.
    """
    from domain_file_services import StagedFileService
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    client.post(
        "/api/v1/modules/machineconfig/compile",
        json={"profile_path": "starter.cfg", "compiler_id": "klipper-to-linuxcnc"},
    )

    staged_service = StagedFileService(root=isolated_machine_config["staged"])
    assert staged_service.mark_read_only() == 0
    assert staged_service.set_read_only("machine.cfg", True) is True

    # Every staged file is still whatever mode the compile wrote
    # (typically 0o644 owned by the test runner). Crucially, the
    # no-op must not have changed those bits.
    staged = isolated_machine_config["staged"]
    for entry in staged.rglob("*"):
        assert entry.stat().st_mode & 0o222, (
            f"staged entry {entry} lost its write bits; "
            f"the no-op should have been a no-op"
        )

def test_compile_unknown_compiler_returns_404(
    tmp_data_root, clean_env, isolated_machine_config
):
    """Unknown compiler id is rejected with 404."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/machineconfig/compile",
        json={"profile_path": "starter.cfg", "compiler_id": "no-such"},
    )
    assert resp.status_code == 404

def test_compile_missing_profile_returns_404(
    tmp_data_root, clean_env, isolated_machine_config
):
    """A profile path that doesn't exist is rejected with 404."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/machineconfig/compile",
        json={"profile_path": "nope.cfg", "compiler_id": "klipper-to-linuxcnc"},
    )
    assert resp.status_code == 404

def test_staged_content_endpoint_returns_text(
    tmp_data_root, clean_env, isolated_machine_config
):
    """``GET /staged/content/{name}`` returns the file text plus read_only=true."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    client.post(
        "/api/v1/modules/machineconfig/compile",
        json={"profile_path": "starter.cfg", "compiler_id": "klipper-to-linuxcnc"},
    )
    resp = client.get("/api/v1/modules/machineconfig/staged/content/machine.cfg")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "machine.cfg"
    assert body["read_only"] is True
    assert "[stepper_x]" in body["content"]

def test_deploy_requires_confirm_flash_when_setting_on(
    tmp_data_root, clean_env, isolated_machine_config
):
    """``POST /deploy`` without confirm_flash returns 400 by default."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    client.post(
        "/api/v1/modules/machineconfig/compile",
        json={"profile_path": "starter.cfg", "compiler_id": "klipper-to-linuxcnc"},
    )
    resp = client.post(
        "/api/v1/modules/machineconfig/deploy",
        json={"confirm_flash": False},
    )
    assert resp.status_code == 400
    assert "confirm_flash" in resp.json()["detail"]

def test_deploy_promotes_staged_into_active(
    tmp_data_root, clean_env, isolated_machine_config
):
    """``POST /deploy`` with confirm_flash=true copies staged → active."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    client.post(
        "/api/v1/modules/machineconfig/compile",
        json={"profile_path": "starter.cfg", "compiler_id": "klipper-to-linuxcnc"},
    )
    resp = client.post(
        "/api/v1/modules/machineconfig/deploy",
        json={"confirm_flash": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert sorted(body["deployed"]) == [
        "config.txt",
        "hardware.json",
        "linuxcnc.ini",
        "machine.cfg",
        "machine.hal",
    ]

    # The active directory now holds the artifacts.
    active_files = sorted(p.name for p in isolated_machine_config["active"].iterdir())
    assert active_files == [
        "config.txt",
        "hardware.json",
        "linuxcnc.ini",
        "machine.cfg",
        "machine.hal",
    ]

    # The machine-name probe reads MACHINE from the active INI.
    resp = client.get("/api/v1/modules/machineconfig/machine-name")
    assert resp.status_code == 200
    # Remora-flavoured template sets ``MACHINE = Remora-XY``.
    assert resp.json()["machine_name"] == "Remora-XY"

def test_deploy_empty_staging_returns_400(
    tmp_data_root, clean_env, isolated_machine_config
):
    """Deploying before a compile step fails fast."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/machineconfig/deploy",
        json={"confirm_flash": True},
    )
    assert resp.status_code == 400

def test_active_endpoint_lists_running_files(
    tmp_data_root, clean_env, isolated_machine_config
):
    """``GET /active`` returns the deployed file list and the machine name."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    client.post(
        "/api/v1/modules/machineconfig/compile",
        json={"profile_path": "starter.cfg", "compiler_id": "klipper-to-linuxcnc"},
    )
    client.post(
        "/api/v1/modules/machineconfig/deploy",
        json={"confirm_flash": True},
    )
    resp = client.get("/api/v1/modules/machineconfig/active")
    assert resp.status_code == 200
    body = resp.json()
    assert body["machine_name"] == "Remora-XY"
    names = sorted(f["name"] for f in body["files"])
    assert names == [
        "config.txt",
        "hardware.json",
        "linuxcnc.ini",
        "machine.cfg",
        "machine.hal",
    ]

def test_active_content_endpoint_returns_text(
    tmp_data_root, clean_env, isolated_machine_config
):
    """``GET /active/content/{name}`` returns the raw text content."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    client.post(
        "/api/v1/modules/machineconfig/compile",
        json={"profile_path": "starter.cfg", "compiler_id": "klipper-to-linuxcnc"},
    )
    client.post(
        "/api/v1/modules/machineconfig/deploy",
        json={"confirm_flash": True},
    )
    resp = client.get("/api/v1/modules/machineconfig/active/content/linuxcnc.ini")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "linuxcnc.ini"
    assert "[EMC]" in body["content"]

def test_machine_name_empty_active_returns_null(
    tmp_data_root, clean_env, isolated_machine_config
):
    """With no active files, the machine-name endpoint returns null."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    resp = client.get("/api/v1/modules/machineconfig/machine-name")
    assert resp.status_code == 200
    assert resp.json()["machine_name"] is None

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

    # Top-level shape.
    assert payload["version"] == "2.1"
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
# Structured-error compile response (issue #99)                           #
# ---------------------------------------------------------------------- #

def test_compile_duplicate_stepper_pin_returns_structured_error(
    tmp_data_root, clean_env, isolated_machine_config
):
    """``POST /compile`` on the issue's example config returns the
    new structured error envelope.

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
        "#Start[mcu]\n"
        "[mcu]\nconnection: remora-spi\ninterface: /dev/ttyACM0\n\n"
        "[stepper_x]\nstep_pin: PG0\ndir_pin: PG1\nenable_pin: !PF15\n\n"
        "[stepper_y]\nstep_pin: PG0\ndir_pin: PG1\nenable_pin: !PF15\n\n"
        "[stepper_z]\nstep_pin: PG0\ndir_pin: PG1\nenable_pin: !PF15\n\n"
        "[extruder]\nstep_pin: PA4\ndir_pin: PA5\nheater_pin: PE3\nsensor_pin: PA1\ncontrol: pid\npid_Kp: 1.0\npid_Ki: 1.0\npid_Kd: 1.0\nmin_temp: 0\nmax_temp: 250\n\n"
        "[heater_bed]\nheater_pin: PB0\nsensor_pin: PB1\ncontrol: watermark\nmin_temp: 0\nmax_temp: 130\n",
        encoding="utf-8",
    )

    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/machineconfig/compile",
        json={
            "profile_path": "duplicate_pins.cfg",
            "compiler_id": "klipper-to-linuxcnc",
        },
    )

    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert "error" in body, "compile must surface the structured envelope"
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

