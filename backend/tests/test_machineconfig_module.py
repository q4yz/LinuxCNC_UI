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

import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.module_registry import ModuleRegistry


# ---------------------------------------------------------------------- #
# Fixtures                                                                #
# ---------------------------------------------------------------------- #


@pytest.fixture()
def isolated_machine_config(monkeypatch, tmp_path):
    """Re-point every machineconfig filesystem constant at ``tmp_path``.

    The test never touches the real ``machine_config/`` directory;
    we give each test a fresh profiles / staged / active subtree so
    the CRUD assertions are deterministic.
    """
    mc = tmp_path / "machine_config"
    profiles = mc / "profiles"
    staged = mc / "ready_for_deploy"
    active = mc / "active"
    for d in (profiles, staged, active):
        d.mkdir(parents=True, exist_ok=True)

    from modules.machineconfig import filesystem

    monkeypatch.setattr(filesystem, "MACHINE_CONFIG_DIR", mc, raising=False)
    monkeypatch.setattr(filesystem, "PROFILES_DIR", profiles, raising=False)
    monkeypatch.setattr(filesystem, "STAGED_DIR", staged, raising=False)
    monkeypatch.setattr(filesystem, "ACTIVE_DIR", active, raising=False)

    # Seed a starter profile that contains the ``#Start`` marker so
    # the inline compile action has something to point at.
    (profiles / "starter.cfg").write_text(
        "#Start\n[printer]\nkinematics: cartesian\nmax_velocity: 250.0\n"
        "[stepper_x]\n    step_pin: PC2\n    dir_pin: PB9\n    enable_pin: !PC3\n"
    )

    return {
        "machine_config": mc,
        "profiles": profiles,
        "staged": staged,
        "active": active,
    }


def _machineconfig_app(tmp_data_root, isolated_machine_config):
    """Build a fresh FastAPI app + registry with the machineconfig module loaded."""
    from modules.machineconfig.module import setup

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, bus=EventBus(), candidates=[setup()])
    return app, reg


# ---------------------------------------------------------------------- #
# Boot / lifecycle                                                        #
# ---------------------------------------------------------------------- #


def test_machineconfig_module_satisfies_protocol(tmp_data_root, clean_env):
    """Machineconfig module is a PluggableModule with the documented manifest."""
    from modules.machineconfig.module import setup

    instance = setup()
    from core.protocols import PluggableModule

    assert isinstance(instance, PluggableModule)
    assert instance.manifest.id == "machineconfig"
    assert instance.manifest.title == "Machine Config"
    assert instance.manifest.settings_panel is True
    assert instance.manifest.sidebar is not None
    assert instance.manifest.sidebar.id == "machineconfig"


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


def test_machineconfig_registry_logs_mounted_summary(
    tmp_data_root, clean_env, isolated_machine_config, caplog
):
    """The boot summary log includes the machineconfig id."""
    from modules.machineconfig.module import setup

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    with caplog.at_level(logging.INFO, logger="core.module_registry"):
        reg.boot(app, bus=EventBus(), candidates=[setup()])
    summary = [
        r.message
        for r in caplog.records
        if "registry: mounted=" in r.message
    ]
    assert summary, "expected the boot summary log line"
    assert "mounted=['machineconfig']" in summary[0]


# ---------------------------------------------------------------------- #
# Compiler registry                                                       #
# ---------------------------------------------------------------------- #


def test_klipper_compiler_is_registered(tmp_data_root, clean_env):
    """The default compiler is registered on package import."""
    from modules.machineconfig.compilers import registry

    assert "klipper-to-linuxcnc" in registry
    compiler = registry.get("klipper-to-linuxcnc")
    assert compiler.id == "klipper-to-linuxcnc"
    assert compiler.title == "Klipper → LinuxCNC"
    assert compiler.source_marker == "#Start"


def test_klipper_compiler_compiles_a_profile(tmp_data_root, clean_env):
    """The compiler produces the four canonical artifacts."""
    from modules.machineconfig.compilers import registry

    compiler = registry.get("klipper-to-linuxcnc")
    src = Path("/app/workspaces/q4yz/LinuxCNC_UI/machine_config/profiles/printer.cfg")
    out = tmp_data_root / "staged"
    out.mkdir()

    artifacts = compiler.compile(src, out)
    names = sorted(p.name for p in artifacts)
    assert names == ["linuxcnc.ini", "machine.cfg", "machine.hal", "remora.json"]

    # Each artifact is non-empty and the machine.cfg is a verbatim copy.
    machine_cfg = (out / "machine.cfg").read_text()
    assert "#Start" not in machine_cfg  # our seed profile doesn't carry the marker
    assert "[stepper_x]" in machine_cfg

    ini = (out / "linuxcnc.ini").read_text()
    assert "[EMC]" in ini
    assert "MACHINE = linuxcnc" in ini


def test_klipper_compiler_has_source_marker(tmp_data_root, clean_env):
    """Marker detection returns True only for files containing ``#Start``."""
    from modules.machineconfig.compilers import registry

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
        "/api/v1/modules/machineconfig/profiles/content/subdir/new.cfg",
        json={"content": "#Start\n[printer]\nkinematics: cartesian\n"},
    )
    assert resp.status_code == 200

    # Read it back.
    resp = client.get(
        "/api/v1/modules/machineconfig/profiles/content/subdir/new.cfg"
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
    resp = client.delete("/api/v1/modules/machineconfig/profiles/subdir/renamed.cfg")
    assert resp.status_code == 200
    resp = client.delete("/api/v1/modules/machineconfig/profiles/subdir")
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
    resp = client.delete("/api/v1/modules/machineconfig/profiles/nonempty")
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
        "linuxcnc.ini",
        "machine.cfg",
        "machine.hal",
        "remora.json",
    ]
    assert len(body["staged"]) == 4

    # ``GET /staged`` mirrors the listing.
    resp = client.get("/api/v1/modules/machineconfig/staged")
    assert resp.status_code == 200
    assert len(resp.json()) == 4


def test_compile_marks_staged_readonly(
    tmp_data_root, clean_env, isolated_machine_config
):
    """After a compile, staged artifacts are write-protected by default."""
    app, _ = _machineconfig_app(tmp_data_root, isolated_machine_config)
    client = TestClient(app)
    client.post(
        "/api/v1/modules/machineconfig/compile",
        json={"profile_path": "starter.cfg", "compiler_id": "klipper-to-linuxcnc"},
    )
    machine_cfg = isolated_machine_config["staged"] / "machine.cfg"
    mode = machine_cfg.stat().st_mode
    assert not (mode & 0o222), "staged files must be read-only after compile"


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
        "linuxcnc.ini",
        "machine.cfg",
        "machine.hal",
        "remora.json",
    ]

    # The active directory now holds the artifacts.
    active_files = sorted(p.name for p in isolated_machine_config["active"].iterdir())
    assert active_files == [
        "linuxcnc.ini",
        "machine.cfg",
        "machine.hal",
        "remora.json",
    ]

    # The machine-name probe reads MACHINE from the active INI.
    resp = client.get("/api/v1/modules/machineconfig/machine-name")
    assert resp.status_code == 200
    assert resp.json()["machine_name"] == "linuxcnc"


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
    assert body["machine_name"] == "linuxcnc"
    names = sorted(f["name"] for f in body["files"])
    assert names == [
        "linuxcnc.ini",
        "machine.cfg",
        "machine.hal",
        "remora.json",
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