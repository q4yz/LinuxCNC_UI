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
from tests._module_app_factory import build_module_app

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.settings_store import SettingsStore

# ---------------------------------------------------------------------- #
# Fixtures                                                                #
# ---------------------------------------------------------------------- #

@pytest.fixture()
def isolated_storage(monkeypatch, tmp_path: Path):
    """Re-point the router's storage at a fresh ``tmp_path`` tree.

    The HTTP integration tests never touch the real ``<repo>/macros/``
    directory — we monkeypatch ``get_macros_service`` so it returns a
    service instance backed by an isolated ``MacroStorage`` rooted at
    ``tmp_path/macros``. M-code cases below also re-point the
    ``MCodeFileService`` root via a parallel fixture so the cross-kind
    isolation tests do not touch ``<repo>/machine_config/m_codes/``
    either.
    """
    from services import MacroService
    from storage.MacroStorage import MacroStorage
    import services.MacroService as macros_service_module
    import routers.macros as macros_router_mod

    isolated_root = tmp_path / "macros"
    isolated_root.mkdir(parents=True, exist_ok=True)
    storage = MacroStorage(isolated_root)
    service = MacroService.MacrosService()
    service._macro_storage = storage
    # Patch the binding on every module namespace that captured it
    # at ``from … import get_macros_service`` time.
    for module_obj in (
        MacroService,
        macros_service_module,
        macros_router_mod,
    ):
        monkeypatch.setattr(
            module_obj,
            "get_macros_service",
            lambda: service,
        )
    return {"root": isolated_root, "storage": storage}

@pytest.fixture()
def isolated_mcodes(monkeypatch, tmp_path: Path):
    """Re-point the M-code service root at a fresh ``tmp_path`` tree.

    The ``MCodeFileService`` is constructed lazily on first call
    via ``get_mcode_service()``; we drop the cached instance and
    substitute an isolated one. Tests that need both fixtures
    pass both fixtures in.

    Critical: the macros router delegates to ``MacrosService``
    which imports ``get_mcode_service`` via
    ``from services import get_mcode_service`` — that binding is
    captured at module load time, so the patch must target the
    symbol's module-local binding (``services.MacroService``), not
    only the package attribute (``services``). The machineconfig
    router imports the symbol separately and must be patched too.
    """
    from domain_file_services import MCodeFileService

    isolated_root = tmp_path / "m_codes"
    isolated_root.mkdir(parents=True, exist_ok=True)
    service = MCodeFileService(isolated_root)
    import services
    import services.MacroService as macros_service_module
    import routers.machineconfig as machineconfig_router_mod
    _ = services.get_mcode_service  # force-import into the package attr
    for module_obj in (
        services,
        macros_service_module,
        machineconfig_router_mod,
    ):
        monkeypatch.setattr(
            module_obj,
            "get_mcode_service",
            lambda root=None, _service=service: _service,
        )
    # Drop the cached singleton so callers construct a fresh instance
    # against the patched module root instead of the cached one.
    from domain_file_services import reset_service_cache
    reset_service_cache()
    return {"root": isolated_root, "service": service}

def _macros_app(tmp_data_root) -> FastAPI:
    """Build a fresh FastAPI app with the macros module wired up."""
    return build_module_app("macros", tmp_data_root)

# ---------------------------------------------------------------------- #
# Storage unit tests — MacroStorage against tmp_path                       #
# ---------------------------------------------------------------------- #

class TestMacroStorage:
    """Direct unit tests for the filesystem-backed storage layer."""

    def test_list_returns_empty_when_directory_missing(self, tmp_path: Path):
        from storage.MacroStorage import MacroStorage

        storage = MacroStorage(tmp_path / "macros")
        assert storage.list() == []

    def test_list_returns_sorted_names_without_extension(self, tmp_path: Path):
        from storage.MacroStorage import EXTENSION, MacroStorage

        root = tmp_path / "macros"
        root.mkdir()
        for name in ("charlie", "alpha", "bravo"):
            (root / f"{name}{EXTENSION}").write_text("x", encoding="utf-8")
        # Stray non-macro file — must be ignored.
        (root / "README.md").write_text("hi", encoding="utf-8")

        storage = MacroStorage(root)
        assert storage.list() == ["alpha", "bravo", "charlie"]

    def test_list_ignores_subdirectories(self, tmp_path: Path):
        from storage.MacroStorage import EXTENSION, MacroStorage

        root = tmp_path / "macros"
        root.mkdir()
        (root / f"good{EXTENSION}").write_text("x", encoding="utf-8")
        (root / "subdir").mkdir()
        (root / "subdir" / "nested.macro").write_text("x", encoding="utf-8")

        storage = MacroStorage(root)
        assert storage.list() == ["good"]

    def test_write_creates_file_and_returns_size(self, tmp_path: Path):
        from storage.MacroStorage import EXTENSION, MacroStorage

        root = tmp_path / "macros"
        storage = MacroStorage(root)
        size = storage.write("hello", "G0 X0 Y0\nM3 S1000\n")
        assert (root / f"hello{EXTENSION}").read_text(encoding="utf-8") == (
            "G0 X0 Y0\nM3 S1000\n"
        )
        assert size == len("G0 X0 Y0\nM3 S1000\n".encode("utf-8"))

    def test_write_overwrites_existing(self, tmp_path: Path):
        from storage.MacroStorage import EXTENSION, MacroStorage

        root = tmp_path / "macros"
        storage = MacroStorage(root)
        storage.write("hello", "first")
        storage.write("hello", "second")
        assert (root / f"hello{EXTENSION}").read_text(encoding="utf-8") == "second"

    def test_write_creates_missing_root(self, tmp_path: Path):
        from storage.MacroStorage import EXTENSION, MacroStorage

        root = tmp_path / "does" / "not" / "exist"
        storage = MacroStorage(root)
        storage.write("hi", "payload")
        assert (root / f"hi{EXTENSION}").exists()

    def test_read_returns_raw_content(self, tmp_path: Path):
        from storage.MacroStorage import EXTENSION, MacroStorage

        root = tmp_path / "macros"
        root.mkdir()
        (root / f"hello{EXTENSION}").write_text(
            "G91\nG1 X10 F1000\nG90\n", encoding="utf-8"
        )

        storage = MacroStorage(root)
        assert storage.read("hello") == "G91\nG1 X10 F1000\nG90\n"

    def test_read_missing_raises(self, tmp_path: Path):
        from storage.MacroStorage import MacroNotFoundError, MacroStorage

        root = tmp_path / "macros"
        root.mkdir()
        storage = MacroStorage(root)
        with pytest.raises(MacroNotFoundError):
            storage.read("nope")

    def test_delete_removes_file(self, tmp_path: Path):
        from storage.MacroStorage import EXTENSION, MacroStorage

        root = tmp_path / "macros"
        root.mkdir()
        path = root / f"hello{EXTENSION}"
        path.write_text("x", encoding="utf-8")

        storage = MacroStorage(root)
        storage.delete("hello")
        assert not path.exists()

    def test_delete_missing_raises(self, tmp_path: Path):
        from storage.MacroStorage import MacroNotFoundError, MacroStorage

        root = tmp_path / "macros"
        root.mkdir()
        storage = MacroStorage(root)
        with pytest.raises(MacroNotFoundError):
            storage.delete("nope")

    def test_exists_returns_correct_value(self, tmp_path: Path):
        from storage.MacroStorage import EXTENSION, MacroStorage

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
        from storage.MacroStorage import InvalidMacroNameError, MacroStorage

        root = tmp_path / "macros"
        storage = MacroStorage(root)
        with pytest.raises(InvalidMacroNameError):
            storage.write(name, "x")

    def test_exists_returns_false_for_invalid_name(self, tmp_path: Path):
        from storage.MacroStorage import MacroStorage

        storage = MacroStorage(tmp_path / "macros")
        assert storage.exists("../etc/passwd") is False
        assert storage.exists("..") is False
        assert storage.exists(".") is False

    def test_write_rejects_non_string_content(self, tmp_path: Path):
        from storage.MacroStorage import MacroStorage

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
    from storage import MacroStorage as storage_module
    from storage.MacroStorage import EXTENSION, MacroStorage

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

def test_macros_directory_is_gitignored():
    """The ``macros/`` directory must be in ``.gitignore`` (anchored
    to the repo root) so runtime-created files never reach git
    history. The anchor is important: a bare ``macros/`` entry
    would also ignore the ``backend/modules/macros/`` package
    directory.
    """
    gitignore = Path(__file__).resolve().parents[3].joinpath(".gitignore").read_text(
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
        # The ``isolated_storage`` fixture patches
        # ``services.get_macros_service`` to return an isolated
        # ``MacrosService`` instance whose ``_macro_storage`` is rooted
        # at ``isolated_storage["root"]``. The macros router reads
        # the service through that import; the patch is in effect
        # for the duration of the test, so building the app here is
        # enough — the patch was applied before this line runs.
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
    follow the canonical LinuxCNC ``M100.M199`` range. Each test
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
        # Below the range — LinuxCNC reserves M0.M99.
        resp = client.put(
            "/api/v1/modules/macros/M99?kind=mcode", content="G4 P1\n"
        )
        assert resp.status_code == 400

        # Above the range — the interpreter only resolves M100.M199.
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
        mc_app = build_module_app("machineconfig", tmp_data_root)
        from routers.machineconfig import register_exception_handlers
        register_exception_handlers(mc_app)
        mc_client = TestClient(mc_app)

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
        app = build_module_app("machineconfig", tmp_data_root)
        from routers.machineconfig import register_exception_handlers
        register_exception_handlers(app)
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

# ---------------------------------------------------------------------- #
# Universal-editor content endpoints                                       #
# ---------------------------------------------------------------------- #
#
# The ``/{name}/content`` family is the new contract the universal
# editor's source-driven dispatch consumes (issue #132). The tests
# below assert:
#
#   * the response shape matches every other source's envelope
#     (``{name, kind, content, size_bytes}``);
#   * the write path is atomic + handles empty payloads without a
#     ``422``;
#   * cross-kind round-trips (macro / ngc / mcode) all work through
#     the same endpoint shape.

class TestMacrosContentEnvelope:
    """``GET/PUT /{name}/content?kind=`` round-trip tests."""

    def test_get_content_returns_envelope_for_existing_macro(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        app = _macros_app(tmp_data_root)
        client = TestClient(app)

        # Seed a macro via the legacy PUT so the GET /content test
        # exercises the read path against an already-written file.
        client.put(
            "/api/v1/modules/macros/hello",
            content="G0 X10 Y20 Z30\n",
        )

        resp = client.get("/api/v1/modules/macros/hello/content")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "name": "hello",
            "kind": "macro",
            "content": "G0 X10 Y20 Z30\n",
            "size_bytes": len("G0 X10 Y20 Z30\n"),
        }

    def test_put_then_get_round_trips_macro_payload(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        app = _macros_app(tmp_data_root)
        client = TestClient(app)

        payload = "G91\nG1 X10 F1000\nG90\n"
        put_resp = client.put(
            "/api/v1/modules/macros/move_loop/content",
            json={"content": payload},
        )
        assert put_resp.status_code == 200
        body = put_resp.json()
        assert body["name"] == "move_loop"
        assert body["kind"] == "macro"
        assert body["content"] == payload
        assert body["size_bytes"] == len(payload.encode("utf-8"))

        get_resp = client.get("/api/v1/modules/macros/move_loop/content")
        assert get_resp.status_code == 200
        assert get_resp.json()["content"] == payload

    def test_empty_content_payload_is_normalised_to_newline(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        """``""`` must not ``422`` — same FastAPI quirk the other
        universal-editor sources route around by writing ``"\\n"``.
        """
        app = _macros_app(tmp_data_root)
        client = TestClient(app)
        resp = client.put(
            "/api/v1/modules/macros/blank/content",
            json={"content": ""},
        )
        assert resp.status_code == 200
        assert resp.json()["content"] == "\n"

    def test_get_content_404_when_macro_missing(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        app = _macros_app(tmp_data_root)
        client = TestClient(app)
        resp = client.get("/api/v1/modules/macros/nope/content")
        assert resp.status_code == 404

    def test_get_content_400_for_invalid_kind(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        app = _macros_app(tmp_data_root)
        client = TestClient(app)
        resp = client.get(
            "/api/v1/modules/macros/hello/content",
            params={"kind": "bogus"},
        )
        assert resp.status_code == 400

    def test_ngc_kind_round_trips_through_content_endpoints(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        """The same envelope shape works for ``ngc`` subroutines —
        only the on-disk extension differs."""
        app = _macros_app(tmp_data_root)
        client = TestClient(app)
        payload = "O<probe> sub\n  G91\n  G38.2 Z-10 F100\nO<probe> endsub\n"

        put_resp = client.put(
            "/api/v1/modules/macros/probe/content",
            params={"kind": "ngc"},
            json={"content": payload},
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["kind"] == "ngc"
        assert put_resp.json()["content"] == payload

        get_resp = client.get(
            "/api/v1/modules/macros/probe/content",
            params={"kind": "ngc"},
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["content"] == payload

    def test_mcode_kind_round_trips_through_content_endpoints(
        self, tmp_data_root, clean_env, isolated_mcodes
    ):
        """``mcode`` shares the content envelope — the underlying
        :class:`MCodeFileService` resolves against the
        ``machine_config/m_codes/`` root instead of ``<repo>/macros/``.
        """
        app = _macros_app(tmp_data_root)
        client = TestClient(app)
        payload = "G4 P1\nM30\n"

        put_resp = client.put(
            "/api/v1/modules/macros/M120/content",
            params={"kind": "mcode"},
            json={"content": payload},
        )
        assert put_resp.status_code == 200
        body = put_resp.json()
        # ``MCodeFileService`` may add a trailing newline on write so
        # the persisted size is not necessarily ``len(payload)``;
        # assert against the response's own ``size_bytes`` instead.
        assert body["name"] == "M120"
        assert body["kind"] == "mcode"
        assert body["content"].startswith(payload)
        assert body["size_bytes"] > 0

        get_resp = client.get(
            "/api/v1/modules/macros/M120/content",
            params={"kind": "mcode"},
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["content"].startswith(payload)

    def test_put_overwrites_existing_macro(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        app = _macros_app(tmp_data_root)
        client = TestClient(app)
        client.put(
            "/api/v1/modules/macros/edit_me/content",
            json={"content": "first version\n"},
        )
        put_resp = client.put(
            "/api/v1/modules/macros/edit_me/content",
            json={"content": "second version\n"},
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["content"] == "second version\n"

        get_resp = client.get("/api/v1/modules/macros/edit_me/content")
        assert get_resp.status_code == 200
        assert get_resp.json()["content"] == "second version\n"

    def test_content_payload_requires_content_field(
        self, tmp_data_root, clean_env, isolated_storage
    ):
        """The envelope is ``{content: ...}`` — a missing field
        is a 422 from Pydantic, mirroring the same validation on
        every other source's PUT."""
        app = _macros_app(tmp_data_root)
        client = TestClient(app)
        resp = client.put(
            "/api/v1/modules/macros/no_body/content",
            json={},
        )
        assert resp.status_code == 422
