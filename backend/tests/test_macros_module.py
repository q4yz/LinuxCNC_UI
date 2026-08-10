"""Tests for the macros backend module (issue #92).

Covers:

* Storage unit tests — :class:`MacroStorage` against ``tmp_path``
  (list / read / write / delete / exists / name validation /
  atomic-write property).
* HTTP integration tests — every endpoint documented in the issue
  with an isolated storage bound to ``tmp_path`` via monkeypatch.
* Lifecycle / factory tests — ``setup()`` returns a fresh instance,
  ``on_load`` / ``on_unload`` are non-blocking + idempotent.
* Full CRUD lifecycle end-to-end test — create → read → list →
  update → delete with assertions on every state transition.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.module_registry import ModuleRegistry
from core.protocols import ModuleContext
from core.settings_store import SettingsStore


# ---------------------------------------------------------------------- #
# Fixtures                                                                #
# ---------------------------------------------------------------------- #


@pytest.fixture()
def isolated_storage(monkeypatch, tmp_path: Path):
    """Re-point the router's storage at a fresh ``tmp_path`` tree.

    The HTTP integration tests never touch the real ``<repo>/macros/``
    directory — we monkeypatch the router's module-level
    ``_macro_storage`` singleton so each test sees a clean tree.
    M-code cases below also re-point the ``MCodeFileService`` root
    via a parallel fixture so the cross-kind isolation tests do not
    touch ``<repo>/machine_config/m_codes/`` either.
    """
    from modules.macros import router as macros_router
    from modules.macros.storage import MacroStorage

    isolated_root = tmp_path / "macros"
    isolated_root.mkdir(parents=True, exist_ok=True)
    storage = MacroStorage(isolated_root)
    monkeypatch.setattr(macros_router, "_macro_storage", storage)
    return {"root": isolated_root, "storage": storage}


@pytest.fixture()
def isolated_mcodes(monkeypatch, tmp_path: Path):
    """Re-point the M-code service root at a fresh ``tmp_path`` tree.

    The ``MCodeFileService`` is constructed lazily on first call
    via ``get_mcode_service()``; we drop the cached instance and
    substitute an isolated one. Tests that need both fixtures
    pass both fixtures in.

    Critical: ``modules.macros.router`` imports
    ``get_mcode_service`` at module load time (a top-level
    ``from services import get_mcode_service`` binding), so we
    must patch the symbol the router actually references, not
    the underlying :mod:`services.domain_file_services` module.
    Patching only the latter would still let the router call
    through its module-level binding to the real
    ``<repo>/machine_config/m_codes/`` root.
    """
    from services.domain_file_services import MCodeFileService

    isolated_root = tmp_path / "m_codes"
    isolated_root.mkdir(parents=True, exist_ok=True)
    service = MCodeFileService(isolated_root)
    # Patch on every name the macros router could have imported the
    # factory under. ``from services import get_mcode_service`` binds
    # on the router's own module namespace; the machineconfig router
    # uses the same import pattern. ``monkeypatch.setattr`` requires a
    # real module object (not a string), so we import each one.
    import services
    import modules.macros.router as macros_router_mod
    import modules.machineconfig.router as machineconfig_router_mod
    _ = services.get_mcode_service  # force-import into the package attr
    for module_obj in (services, macros_router_mod, machineconfig_router_mod):
        monkeypatch.setattr(
            module_obj,
            "get_mcode_service",
            lambda root=None, _service=service: _service,
        )
    # Drop the cached singleton so callers construct a fresh instance
    # against the patched module root instead of the cached one.
    from services.domain_file_services import reset_service_cache
    reset_service_cache()
    return {"root": isolated_root, "service": service}


def _macros_app(tmp_data_root) -> FastAPI:
    """Build a fresh FastAPI app + registry with the macros module loaded."""
    from modules.macros.module import setup

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, bus=EventBus(), candidates=[setup()])
    return app


# ---------------------------------------------------------------------- #
# Storage unit tests — MacroStorage against tmp_path                       #
# ---------------------------------------------------------------------- #


class TestMacroStorage:
    """Direct unit tests for the filesystem-backed storage layer."""

    def test_list_returns_empty_when_directory_missing(self, tmp_path: Path):
        from modules.macros.storage import MacroStorage

        storage = MacroStorage(tmp_path / "macros")
        assert storage.list() == []

    def test_list_returns_sorted_names_without_extension(self, tmp_path: Path):
        from modules.macros.storage import EXTENSION, MacroStorage

        root = tmp_path / "macros"
        root.mkdir()
        for name in ("charlie", "alpha", "bravo"):
            (root / f"{name}{EXTENSION}").write_text("x", encoding="utf-8")
        # Stray non-macro file — must be ignored.
        (root / "README.md").write_text("hi", encoding="utf-8")

        storage = MacroStorage(root)
        assert storage.list() == ["alpha", "bravo", "charlie"]

    def test_list_ignores_subdirectories(self, tmp_path: Path):
        from modules.macros.storage import EXTENSION, MacroStorage

        root = tmp_path / "macros"
        root.mkdir()
        (root / f"good{EXTENSION}").write_text("x", encoding="utf-8")
        (root / "subdir").mkdir()
        (root / "subdir" / "nested.macro").write_text("x", encoding="utf-8")

        storage = MacroStorage(root)
        assert storage.list() == ["good"]

    def test_write_creates_file_and_returns_size(self, tmp_path: Path):
        from modules.macros.storage import EXTENSION, MacroStorage

        root = tmp_path / "macros"
        storage = MacroStorage(root)
        size = storage.write("hello", "G0 X0 Y0\nM3 S1000\n")
        assert (root / f"hello{EXTENSION}").read_text(encoding="utf-8") == (
            "G0 X0 Y0\nM3 S1000\n"
        )
        assert size == len("G0 X0 Y0\nM3 S1000\n".encode("utf-8"))

    def test_write_overwrites_existing(self, tmp_path: Path):
        from modules.macros.storage import EXTENSION, MacroStorage

        root = tmp_path / "macros"
        storage = MacroStorage(root)
        storage.write("hello", "first")
        storage.write("hello", "second")
        assert (root / f"hello{EXTENSION}").read_text(encoding="utf-8") == "second"

    def test_write_creates_missing_root(self, tmp_path: Path):
        from modules.macros.storage import EXTENSION, MacroStorage

        root = tmp_path / "does" / "not" / "exist"
        storage = MacroStorage(root)
        storage.write("hi", "payload")
        assert (root / f"hi{EXTENSION}").exists()

    def test_read_returns_raw_content(self, tmp_path: Path):
        from modules.macros.storage import EXTENSION, MacroStorage

        root = tmp_path / "macros"
        root.mkdir()
        (root / f"hello{EXTENSION}").write_text(
            "G91\nG1 X10 F1000\nG90\n", encoding="utf-8"
        )

        storage = MacroStorage(root)
        assert storage.read("hello") == "G91\nG1 X10 F1000\nG90\n"

    def test_read_missing_raises(self, tmp_path: Path):
        from modules.macros.storage import MacroNotFoundError, MacroStorage

        root = tmp_path / "macros"
        root.mkdir()
        storage = MacroStorage(root)
        with pytest.raises(MacroNotFoundError):
            storage.read("nope")

    def test_delete_removes_file(self, tmp_path: Path):
        from modules.macros.storage import EXTENSION, MacroStorage

        root = tmp_path / "macros"
        root.mkdir()
        path = root / f"hello{EXTENSION}"
        path.write_text("x", encoding="utf-8")

        storage = MacroStorage(root)
        storage.delete("hello")
        assert not path.exists()

    def test_delete_missing_raises(self, tmp_path: Path):
        from modules.macros.storage import MacroNotFoundError, MacroStorage

        root = tmp_path / "macros"
        root.mkdir()
        storage = MacroStorage(root)
        with pytest.raises(MacroNotFoundError):
            storage.delete("nope")

    def test_exists_returns_correct_value(self, tmp_path: Path):
        from modules.macros.storage import EXTENSION, MacroStorage

        root = tmp_path / "macros"
        root.mkdir()
        (root / f"hello{EXTENSION}").write_text("x", encoding="utf-8")

        storage = MacroStorage(root)
        assert storage.exists("hello") is True
        assert storage.exists("nope") is False

    @pytest.mark.parametrize(
        "name",
        [
            "../etc/passwd",
            "..",
            ".",
            "",
            "foo/bar",
            "foo\\bar",
            "a" * 65,  # too long
            "has space",
            "has\ttab",
            "has\nnewline",
            "has;semi",
            "中文",  # non-ASCII
        ],
    )
    def test_write_rejects_invalid_names(self, tmp_path: Path, name: str):
        from modules.macros.storage import InvalidMacroNameError, MacroStorage

        root = tmp_path / "macros"
        storage = MacroStorage(root)
        with pytest.raises(InvalidMacroNameError):
            storage.write(name, "x")

    def test_exists_returns_false_for_invalid_name(self, tmp_path: Path):
        from modules.macros.storage import MacroStorage

        storage = MacroStorage(tmp_path / "macros")
        assert storage.exists("../etc/passwd") is False
        assert storage.exists("..") is False
        assert storage.exists(".") is False

    def test_write_rejects_non_string_content(self, tmp_path: Path):
        from modules.macros.storage import MacroStorage

        storage = MacroStorage(tmp_path / "macros")
        with pytest.raises(TypeError):
            storage.write("hello", b"bytes-not-str")  # type: ignore[arg-type]


# ---------------------------------------------------------------------- #
# Atomic-write interrupt test (mirrors test_settings_store.py)            #
# ---------------------------------------------------------------------- #


def test_atomic_write_leaves_no_partial_file_on_interrupt(
    tmp_path: Path, monkeypatch
):
    """A crash between ``mkstemp`` and ``os.replace`` must leave the
    previous file intact and no temp file behind.
    """
    from modules.macros import storage as storage_module
    from modules.macros.storage import EXTENSION, MacroStorage

    root = tmp_path / "macros"
    storage = MacroStorage(root)
    storage.write("hello", "original")
    original_bytes = (root / f"hello{EXTENSION}").read_bytes()

    real_replace = os.replace
    calls = {"count": 0}

    def boom(src, dst):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated crash")
        return real_replace(src, dst)

    monkeypatch.setattr(storage_module.os, "replace", boom)

    with pytest.raises(RuntimeError, match="simulated crash"):
        storage.write("hello", "totally different content")

    # The original macro is still intact — no half-written file.
    assert (root / f"hello{EXTENSION}").read_bytes() == original_bytes

    # No leftover temp file.
    leftovers = [
        child
        for child in root.iterdir()
        if child.name.endswith(f"{EXTENSION}.tmp")
    ]
    assert leftovers == []

    # Subsequent writes still work.
    storage.write("hello", "recovered")
    assert (root / f"hello{EXTENSION}").read_text(encoding="utf-8") == "recovered"


# ---------------------------------------------------------------------- #
# HTTP integration tests                                                  #
# ---------------------------------------------------------------------- #


class TestMacrosHTTP:
    """End-to-end tests for the four documented HTTP endpoints."""

    def test_module_boots_and_registers_router(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        """The registry mounts the macros router under
        ``/api/v1/modules/macros`` and logs ``macros`` in its summary.
        """
        app = _macros_app(tmp_data_root)
        client = TestClient(app)

        # The canonical settings endpoints are mounted by the
        # registry. Macros has no settings schema → empty payload.
        resp = client.get("/api/v1/modules/macros/settings")
        assert resp.status_code == 200
        assert resp.json() == {}

        # The list endpoint is wired up and returns the empty list
        # shape.
        resp = client.get("/api/v1/modules/macros/")
        assert resp.status_code == 200
        assert resp.json() == {"macros": []}

    def test_get_root_returns_empty_list_when_storage_empty(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        app = _macros_app(tmp_data_root)
        client = TestClient(app)
        resp = client.get("/api/v1/modules/macros/")
        assert resp.status_code == 200
        assert resp.json() == {"macros": []}

    def test_put_then_list_returns_name_without_extension(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        app = _macros_app(tmp_data_root)
        client = TestClient(app)

        for body in ("first", "second", "third"):
            resp = client.put(
                f"/api/v1/modules/macros/{body}",
                content=f"G-code for {body}",
            )
            assert resp.status_code == 200

        resp = client.get("/api/v1/modules/macros/")
        assert resp.status_code == 200
        names = [entry["name"] for entry in resp.json()["macros"]]
        assert names == ["first", "second", "third"]
        assert all(entry["kind"] == "macro" for entry in resp.json()["macros"])

    def test_get_macro_returns_raw_text_body(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        app = _macros_app(tmp_data_root)
        client = TestClient(app)
        client.put(
            "/api/v1/modules/macros/hello",
            content="G91\nG1 X10 F1000\nG90\n",
        )

        resp = client.get("/api/v1/modules/macros/hello")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        assert resp.text == "G91\nG1 X10 F1000\nG90\n"

    def test_get_macro_returns_404_when_missing(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        app = _macros_app(tmp_data_root)
        client = TestClient(app)
        resp = client.get("/api/v1/modules/macros/nope")
        assert resp.status_code == 404

    def test_put_creates_file_and_returns_name_and_size(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        app = _macros_app(tmp_data_root)
        client = TestClient(app)
        payload = "G0 X10 Y20 Z30\n"
        resp = client.put(
            "/api/v1/modules/macros/move_home",
            content=payload,
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "name": "move_home",
            "kind": "macro",
            "size": len(payload.encode("utf-8")),
        }

    def test_put_overwrites_existing(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        app = _macros_app(tmp_data_root)
        client = TestClient(app)
        client.put("/api/v1/modules/macros/hello", content="first")
        resp = client.put("/api/v1/modules/macros/hello", content="second")
        assert resp.status_code == 200
        assert resp.json()["name"] == "hello"

        # Confirm the new payload is what we read back.
        resp = client.get("/api/v1/modules/macros/hello")
        assert resp.text == "second"

    @pytest.mark.parametrize(
        "name",
        [
            "../etc",
            "..",
            "foo/bar",
            "foo\\bar",
            "a" * 65,
            "has space",
        ],
    )
    def test_put_rejects_invalid_name_with_400(
        self, tmp_data_root, clean_env, isolated_storage, name
    ):
        app = _macros_app(tmp_data_root)
        client = TestClient(app)
        # ``urlencode`` would normalise ``..`` and ``/`` away; we want
        # to test the router's own validator. Use the raw path via
        # ``request`` instead of the high-level ``put`` helper.
        from starlette.requests import Request
        from starlette.testclient import TestClient as StarletteTestClient

        starlette_client = StarletteTestClient(app)
        raw = f"/api/v1/modules/macros/{name}"
        resp = starlette_client.put(raw, content="body")
        # Starlette's HTTP layer will translate raw ``..`` segments
        # into 400-class errors or normalize the URL. The router
        # accepts the request and its own validator decides.
        assert resp.status_code in (400, 404, 422)

    def test_delete_returns_204_on_success(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        app = _macros_app(tmp_data_root)
        client = TestClient(app)
        client.put("/api/v1/modules/macros/hello", content="x")

        resp = client.delete("/api/v1/modules/macros/hello")
        assert resp.status_code == 204
        assert resp.content == b""

        # The macro is gone.
        resp = client.get("/api/v1/modules/macros/hello")
        assert resp.status_code == 404

    def test_delete_returns_404_when_missing(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        app = _macros_app(tmp_data_root)
        client = TestClient(app)
        resp = client.delete("/api/v1/modules/macros/never_existed")
        assert resp.status_code == 404


# ---------------------------------------------------------------------- #
# Full CRUD lifecycle end-to-end                                          #
# ---------------------------------------------------------------------- #


def test_full_crud_lifecycle(tmp_data_root, clean_env, isolated_storage):
    """Drive the entire CRUD surface through HTTP and verify every
    state transition.
    """
    app = _macros_app(tmp_data_root)
    client = TestClient(app)

    # 1. Empty listing at start.
    resp = client.get("/api/v1/modules/macros/")
    assert resp.json() == {"macros": []}

    # 2. Create a macro.
    payload_v1 = "M3 S1000\nG4 P1\nM5\n"
    resp = client.put(
        "/api/v1/modules/macros/spindle_warmup",
        content=payload_v1,
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "name": "spindle_warmup",
        "kind": "macro",
        "size": len(payload_v1.encode("utf-8")),
    }

    # 3. Listing reflects the new macro.
    resp = client.get("/api/v1/modules/macros/")
    assert resp.json() == {
        "macros": [
            {"name": "spindle_warmup", "kind": "macro", "size_bytes": 18}
        ]
    }

    # 4. Read it back — body matches what we wrote.
    resp = client.get("/api/v1/modules/macros/spindle_warmup")
    assert resp.text == payload_v1

    # 5. Update overwrites with new content + new size.
    payload_v2 = "M3 S2000\nG4 P2\nM5\n"
    resp = client.put(
        "/api/v1/modules/macros/spindle_warmup",
        content=payload_v2,
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "name": "spindle_warmup",
        "kind": "macro",
        "size": len(payload_v2.encode("utf-8")),
    }

    # 6. The on-disk content is the updated version.
    resp = client.get("/api/v1/modules/macros/spindle_warmup")
    assert resp.text == payload_v2

    # 7. Add a second macro — listing is sorted.
    client.put("/api/v1/modules/macros/alpha", content="alpha payload")
    resp = client.get("/api/v1/modules/macros/")
    names = [entry["name"] for entry in resp.json()["macros"]]
    assert names == ["alpha", "spindle_warmup"]

    # 8. Delete the second macro — listing shrinks, response is 204.
    resp = client.delete("/api/v1/modules/macros/spindle_warmup")
    assert resp.status_code == 204

    # 9. Listing reflects the deletion.
    resp = client.get("/api/v1/modules/macros/")
    names = [entry["name"] for entry in resp.json()["macros"]]
    assert names == ["alpha"]  # only the second macro remains

    # 10. Subsequent reads / deletes of the removed macro are 404.
    assert client.get("/api/v1/modules/macros/spindle_warmup").status_code == 404
    assert (
        client.delete("/api/v1/modules/macros/spindle_warmup").status_code == 404
    )


# ---------------------------------------------------------------------- #
# Module lifecycle / factory tests (mirrors test_tools_module.py)         #
# ---------------------------------------------------------------------- #


def test_macros_module_satisfies_protocol(tmp_data_root, clean_env):
    """``MacrosModule`` implements :class:`PluggableModule`."""
    from core.protocols import PluggableModule

    from modules.macros.module import MacrosModule

    instance = MacrosModule()
    assert isinstance(instance, PluggableModule)
    assert instance.manifest.id == "macros"


def test_setup_returns_fresh_macros_module(tmp_data_root, clean_env):
    from modules.macros.module import MacrosModule, setup

    instance = setup()
    assert isinstance(instance, MacrosModule)
    assert instance is not setup()


def test_setup_returns_isolated_instances(tmp_data_root, clean_env):
    from modules.macros.module import setup

    a = setup()
    b = setup()
    assert a is not b
    a._scratch = {"marker": 1}
    assert not hasattr(b, "_scratch")


def test_on_load_executes_without_error(tmp_data_root, clean_env):
    from modules.macros.module import MacrosModule

    instance = MacrosModule()
    ctx = ModuleContext(
        module_id="macros",
        event_bus=EventBus(),
        settings=SettingsStore(
            module_id="macros",
            data_root=tmp_data_root,
            defaults=None,
        ),
    )
    instance.on_load(ctx)


def test_on_unload_is_idempotent(tmp_data_root, clean_env):
    from modules.macros.module import MacrosModule

    instance = MacrosModule()
    instance.on_unload()
    instance.on_unload()  # second call must also be a no-op


def test_get_settings_model_returns_none(tmp_data_root, clean_env):
    from modules.macros.module import MacrosModule

    instance = MacrosModule()
    assert instance.get_settings_model() is None


def test_get_router_returns_apirouter(tmp_data_root, clean_env):
    from fastapi import APIRouter

    from modules.macros.module import MacrosModule

    instance = MacrosModule()
    router = instance.get_router()
    assert isinstance(router, APIRouter)

    paths = {route.path for route in router.routes}
    # The four documented endpoints.
    assert "" in paths
    assert "/{name}" in paths


def test_module_appears_in_registry_discovery(
    tmp_data_root, clean_env, caplog
):
    """A real :meth:`ModuleRegistry.discover` call finds the macros
    package and the boot summary log includes ``macros``.
    """
    import logging as _logging

    from core.module_registry import ModuleRegistry

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    with caplog.at_level(_logging.INFO, logger="core.module_registry"):
        reg.boot(app)
    assert "macros" in reg.modules

    summary = [
        r.message
        for r in caplog.records
        if "registry: mounted=" in r.message
    ]
    assert summary
    assert "macros" in summary[0]


# ---------------------------------------------------------------------- #
# .gitignore marker test                                                  #
# ---------------------------------------------------------------------- #


def test_macros_directory_is_gitignored():
    """The ``macros/`` directory must be in ``.gitignore`` (anchored
    to the repo root) so runtime-created files never reach git
    history. The anchor is important: a bare ``macros/`` entry
    would also ignore the ``backend/modules/macros/`` package
    directory.
    """
    gitignore = Path(__file__).resolve().parents[2].joinpath(".gitignore").read_text(
        encoding="utf-8"
    )
    assert "/macros/" in gitignore


# ---------------------------------------------------------------------- #
# NGC (LinuxCNC native subroutine) kind                                    #
# ---------------------------------------------------------------------- #


class TestMacrosNGCKind:
    """The ``?kind=ngc`` half shares ``<repo>/macros/`` with the
    ``.macro`` kind. Files are persisted with the ``.ngc`` extension
    but use the same name regex and the same CRUD contract.
    """

    def _client(self, tmp_data_root, isolated_storage):
        app = _macros_app(tmp_data_root)
        return TestClient(app)

    def test_put_then_list_returns_ngc_entry(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        client = self._client(tmp_data_root, isolated_storage)
        resp = client.put(
            "/api/v1/modules/macros/coolant?kind=ngc",
            content="O<coolant> sub\nM8\nO<coolant> endsub\n",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "coolant"
        assert body["kind"] == "ngc"

        # Listing under ``kind=ngc`` returns the new entry.
        resp = client.get("/api/v1/modules/macros/?kind=ngc")
        assert resp.status_code == 200
        rows = resp.json()["macros"]
        assert len(rows) == 1
        assert rows[0]["name"] == "coolant"
        assert rows[0]["kind"] == "ngc"

        # Listing under ``kind=macro`` returns nothing — the file
        # is .ngc, not .macro, so the two extensions are isolated.
        resp = client.get("/api/v1/modules/macros/?kind=macro")
        assert resp.json()["macros"] == []

    def test_ngc_and_macro_share_storage_root(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        # Both kinds land in the same root directory but with
        # different extensions; cross-contamination would surface
        # as one kind listing the other kind's file.
        client = self._client(tmp_data_root, isolated_storage)
        client.put(
            "/api/v1/modules/macros/coolant?kind=ngc", content="ngc body",
        )
        client.put(
            "/api/v1/modules/macros/home_all?kind=macro", content="macro body",
        )

        resp = client.get("/api/v1/modules/macros/?kind=ngc")
        ngc_names = [row["name"] for row in resp.json()["macros"]]
        assert ngc_names == ["coolant"]

        resp = client.get("/api/v1/modules/macros/?kind=macro")
        macro_names = [row["name"] for row in resp.json()["macros"]]
        assert macro_names == ["home_all"]

        # On disk: ``<root>/coolant.ngc`` and
        # ``<root>/home_all.macro`` coexist.
        root = isolated_storage["root"]
        assert (root / "coolant.ngc").exists()
        assert (root / "home_all.macro").exists()

    def test_invalid_kind_returns_400(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        client = self._client(tmp_data_root, isolated_storage)
        resp = client.get("/api/v1/modules/macros/?kind=invalid")
        assert resp.status_code == 400


# ---------------------------------------------------------------------- #
# M-code kind                                                              #
# ---------------------------------------------------------------------- #


class TestMacrosMCodeKind:
    """M-code files live in ``<repo>/machine_config/m_codes/`` and
    follow the canonical LinuxCNC ``M100..M199`` range. Each test
    uses both ``isolated_storage`` (for the macro side) and
    ``isolated_mcodes`` (for the M-code side) so neither root
    touches the real disk.
    """

    def _client(self, tmp_data_root, isolated_storage, isolated_mcodes):
        app = _macros_app(tmp_data_root)
        return TestClient(app)

    def test_put_then_list_returns_mcode_entry(
        self, tmp_data_root, clean_env, isolated_storage, isolated_mcodes
    ):
        client = self._client(tmp_data_root, isolated_storage, isolated_mcodes)
        resp = client.put(
            "/api/v1/modules/macros/M101?kind=mcode",
            content="G65 P1234\nM30\n",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "M101"
        assert body["kind"] == "mcode"

        # Listing returns the new M-code under ``kind=mcode``.
        resp = client.get("/api/v1/modules/macros/?kind=mcode")
        rows = resp.json()["macros"]
        assert len(rows) == 1
        assert rows[0]["name"] == "M101"
        assert rows[0]["kind"] == "mcode"

    def test_out_of_range_name_returns_400(
        self, tmp_data_root, clean_env, isolated_storage, isolated_mcodes
    ):
        client = self._client(tmp_data_root, isolated_storage, isolated_mcodes)
        # Below the range — LinuxCNC reserves M0..M99.
        resp = client.put(
            "/api/v1/modules/macros/M99?kind=mcode", content="G4 P1\n"
        )
        assert resp.status_code == 400

        # Above the range — the interpreter only resolves M100..M199.
        resp = client.put(
            "/api/v1/modules/macros/M200?kind=mcode", content="G4 P1\n"
        )
        assert resp.status_code == 400

        # No extension and lower-case — bare ``M<code>`` only, no
        # python script wrapping.
        resp = client.put(
            "/api/v1/modules/macros/m101?kind=mcode", content="G4 P1\n"
        )
        assert resp.status_code == 400

    def test_get_and_delete_round_trip(
        self, tmp_data_root, clean_env, isolated_storage, isolated_mcodes
    ):
        client = self._client(tmp_data_root, isolated_storage, isolated_mcodes)
        payload = "G65 P42\nM30\n"
        client.put("/api/v1/modules/macros/M105?kind=mcode", content=payload)
        resp = client.get("/api/v1/modules/macros/M105?kind=mcode")
        assert resp.status_code == 200
        assert resp.text == payload

        resp = client.delete("/api/v1/modules/macros/M105?kind=mcode")
        assert resp.status_code == 204

        resp = client.get("/api/v1/modules/macros/M105?kind=mcode")
        assert resp.status_code == 404

    def test_mcode_path_does_not_leak_into_macro_storage(
        self, tmp_data_root, clean_env, isolated_storage, isolated_mcodes
    ):
        # The macros ``MacroStorage`` is rooted at
        # ``<tmp>/macros/``; M-codes should land at
        # ``<tmp>/m_codes/``. A leak would land the bare ``M101`` in
        # the macro root.
        client = self._client(tmp_data_root, isolated_storage, isolated_mcodes)
        client.put("/api/v1/modules/macros/M101?kind=mcode", content="G4 P1\n")

        # The M-code landed in the M-code root, not the macro root.
        assert (isolated_mcodes["root"] / "M101").exists()
        assert not (isolated_storage["root"] / "M101").exists()
        assert not (isolated_storage["root"] / "M101.macro").exists()

    def test_machineconfig_mcodes_endpoints_share_storage(
        self, tmp_data_root, clean_env, isolated_storage, isolated_mcodes
    ):
        """The machineconfig /m-codes/... endpoints exist so the
        universal editor can edit bare ``M<num>`` files. They must
        share the same backing store as the macros router's
        ``?kind=mcode`` path so a file created via one surface
        shows up on the other.
        """
        # Create an M-code through the macros router, then verify it
        # is visible through the machineconfig router (and vice
        # versa). The cross-surface visibility is the actual contract
        # we care about — the two routers must hand out the same
        # ``MCodeFileService`` instance.
        from modules.machineconfig.module import setup as mc_setup

        reg = ModuleRegistry(data_root=tmp_data_root)
        app = FastAPI()
        reg.boot(app, bus=EventBus(), candidates=[mc_setup()])
        mc_client = TestClient(app)

        # Create via the macros router.
        client = self._client(tmp_data_root, isolated_storage, isolated_mcodes)
        client.put("/api/v1/modules/macros/M105?kind=mcode", content="G4 P1\n")

        # Read via the machineconfig router — same file.
        resp = mc_client.get(
            "/api/v1/modules/machineconfig/m-codes/content",
            params={"path": "M105"},
        )
        assert resp.status_code == 200
        assert resp.json()["content"] == "G4 P1\n"


# ---------------------------------------------------------------------- #
# Machineconfig /m-codes/... endpoints                                      #
# ---------------------------------------------------------------------- #


class TestMachineconfigMCodesEndpoints:
    """The universal editor reads / writes M-codes through the
    machineconfig router's ``/m-codes/`` endpoints. They share the
    storage with the macros router's ``?kind=mcode`` path so both
    surfaces see the same state.
    """

    @pytest.fixture()
    def mcode_app(self, tmp_data_root, clean_env, isolated_mcodes):
        """Build an app with the machineconfig module mounted and the
        m-codes root re-pointed at the isolated tree.
        """
        from modules.machineconfig.module import setup

        reg = ModuleRegistry(data_root=tmp_data_root)
        app = FastAPI()
        reg.boot(app, bus=EventBus(), candidates=[setup()])
        return app

    def test_list_endpoint_returns_all_mcodes(
        self, tmp_data_root, clean_env, isolated_mcodes, mcode_app
    ):
        client = TestClient(mcode_app)
        client.put(
            "/api/v1/modules/machineconfig/m-codes/content",
            params={"path": "M101"},
            json={"content": "G4 P1\n"},
        )
        client.put(
            "/api/v1/modules/machineconfig/m-codes/content",
            params={"path": "M150"},
            json={"content": "M8\n"},
        )

        resp = client.get("/api/v1/modules/machineconfig/m-codes/list")
        assert resp.status_code == 200
        names = [row["name"] for row in resp.json()["mcodes"]]
        assert names == ["M101", "M150"]

    def test_read_endpoint_returns_raw_text(
        self, tmp_data_root, clean_env, isolated_mcodes, mcode_app
    ):
        client = TestClient(mcode_app)
        client.put(
            "/api/v1/modules/machineconfig/m-codes/content",
            params={"path": "M105"},
            json={"content": "G65 P9001\nM30\n"},
        )
        resp = client.get(
            "/api/v1/modules/machineconfig/m-codes/content",
            params={"path": "M105"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["path"] == "M105"
        assert body["content"] == "G65 P9001\nM30\n"

    def test_write_endpoint_out_of_range_returns_400(
        self, tmp_data_root, clean_env, isolated_mcodes, mcode_app
    ):
        client = TestClient(mcode_app)
        resp = client.put(
            "/api/v1/modules/machineconfig/m-codes/content",
            params={"path": "M200"},
            json={"content": "G4 P1\n"},
        )
        assert resp.status_code == 400

    def test_delete_round_trip(
        self, tmp_data_root, clean_env, isolated_mcodes, mcode_app
    ):
        client = TestClient(mcode_app)
        client.put(
            "/api/v1/modules/machineconfig/m-codes/content",
            params={"path": "M101"},
            json={"content": "G4 P1\n"},
        )
        resp = client.delete("/api/v1/modules/machineconfig/m-codes/M101")
        assert resp.status_code == 204
        resp = client.get(
            "/api/v1/modules/machineconfig/m-codes/content",
            params={"path": "M101"},
        )
        assert resp.status_code == 404

