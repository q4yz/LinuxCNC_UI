"""CRUD tests for the macros module service and HTTP boundary."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.modules.macros import MacroFileService, MacroNotFoundError
from backend.modules.macros.router import create_router
from backend.modules.macros.service import MACRO_SUFFIX


# ---------------------------------------------------------------------- #
# Service-level fixtures & tests                                          #
# ---------------------------------------------------------------------- #


@pytest.fixture
def macro_service(tmp_path: Path) -> MacroFileService:
    return MacroFileService(tmp_path)


def test_crud_lifecycle(macro_service: MacroFileService) -> None:
    macro_service.write_macro("hello", "G0 X0\n")
    macro_service.write_macro("world", "G0 X10\n")
    assert macro_service.list_macros() == ["hello", "world"]
    assert macro_service.read_macro("hello") == "G0 X0\n"
    macro_service.write_macro("hello", "G0 X99\n")
    assert macro_service.read_macro("hello") == "G0 X99\n"
    macro_service.delete_macro("hello")
    assert macro_service.list_macros() == ["world"]
    with pytest.raises(MacroNotFoundError):
        macro_service.delete_macro("hello")


def test_files_use_macro_extension(macro_service: MacroFileService) -> None:
    macro_service.write_macro("alpha", "payload")
    assert (macro_service.storage_dir / f"alpha{MACRO_SUFFIX}").is_file()
    assert macro_service.list_macros() == ["alpha"]


def test_missing_read_and_delete_raise(tmp_path: Path) -> None:
    service = MacroFileService(tmp_path)
    with pytest.raises(MacroNotFoundError):
        service.read_macro("missing")
    with pytest.raises(MacroNotFoundError):
        service.delete_macro("missing")


def test_invalid_names_and_content(tmp_path: Path) -> None:
    service = MacroFileService(tmp_path)
    with pytest.raises(ValueError):
        service.write_macro("", "content")
    with pytest.raises(ValueError):
        service.write_macro("bad.txt", "content")
    with pytest.raises(TypeError):
        service.write_macro("valid", b"content")  # type: ignore[arg-type]


def test_missing_storage_directory_lists_empty(tmp_path: Path) -> None:
    service = MacroFileService(tmp_path / "nested")
    assert service.list_macros() == []


# ---------------------------------------------------------------------- #
# HTTP boundary tests (router mounted on a throwaway FastAPI app)         #
# ---------------------------------------------------------------------- #


@pytest.fixture
def router_client(tmp_path: Path) -> TestClient:
    """Mount the macros router on a fresh FastAPI app bound to ``tmp_path``.

    Every test gets an isolated ``MacroFileService`` whose storage
    directory is the per-test ``tmp_path``, so the real ``./macros/``
    directory is never touched (issue waiver: no path-traversal / no
    sandboxing, so the storage directory must be supplied explicitly
    to keep the suite hermetic).
    """
    service = MacroFileService(tmp_path)
    app = FastAPI()
    app.include_router(
        create_router(service),
        prefix="/api/v1/modules/macros",
        tags=["modules:macros"],
    )
    return TestClient(app)


def test_router_list_strips_macro_suffix(router_client: TestClient) -> None:
    """``GET /`` returns bare names (no ``.macro``) for the UI list.

    Seed two macros through ``PUT`` so the router exercises the
    on-disk files; the HTTP endpoint must reflect what the service
    wrote.
    """
    router_client.put(
        "/api/v1/modules/macros/alpha",
        json={"content": "G0 X0\n"},
    )
    router_client.put(
        "/api/v1/modules/macros/beta",
        json={"content": "G0 X10\n"},
    )
    resp = router_client.get("/api/v1/modules/macros/")
    assert resp.status_code == 200
    assert resp.json() == ["alpha", "beta"]


def test_router_read_returns_raw_contents(router_client: TestClient) -> None:
    """``GET /{name}`` returns the raw string contents of the file."""
    router_client.put(
        "/api/v1/modules/macros/payload",
        json={"content": "G0 X1\nG0 X2\n"},
    )
    resp = router_client.get("/api/v1/modules/macros/payload")
    assert resp.status_code == 200
    assert resp.text == "G0 X1\nG0 X2\n"


def test_router_read_missing_returns_404(router_client: TestClient) -> None:
    """``GET /{name}`` yields a clean 404 when the macro is absent."""
    resp = router_client.get("/api/v1/modules/macros/missing")
    assert resp.status_code == 404
    body = resp.json()
    assert "detail" in body
    assert "missing" in body["detail"]


def test_router_write_creates_then_updates_atomically(
    router_client: TestClient,
) -> None:
    """``PUT /{name}`` creates a new file and overwrites an existing one."""
    # Create.
    resp = router_client.put(
        "/api/v1/modules/macros/greeting",
        json={"content": "first\n"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"name": "greeting"}
    read = router_client.get("/api/v1/modules/macros/greeting")
    assert read.text == "first\n"

    # Update — the second PUT must overwrite, not append.
    resp = router_client.put(
        "/api/v1/modules/macros/greeting",
        json={"content": "second\n"},
    )
    assert resp.status_code == 200
    read = router_client.get("/api/v1/modules/macros/greeting")
    assert read.text == "second\n"


def test_router_write_rejects_invalid_name(router_client: TestClient) -> None:
    """A name that carries a non-``.macro`` suffix is rejected with 400."""
    resp = router_client.put(
        "/api/v1/modules/macros/bad.txt",
        json={"content": "x"},
    )
    assert resp.status_code == 400


def test_router_delete_removes_file(router_client: TestClient) -> None:
    """``DELETE /{name}`` removes the macro and returns the bare name."""
    router_client.put(
        "/api/v1/modules/macros/doomed",
        json={"content": "x"},
    )
    resp = router_client.delete("/api/v1/modules/macros/doomed")
    assert resp.status_code == 200
    assert resp.json() == {"name": "doomed"}
    # Confirm the read now 404s.
    follow_up = router_client.get("/api/v1/modules/macros/doomed")
    assert follow_up.status_code == 404


def test_router_delete_missing_returns_404(router_client: TestClient) -> None:
    """``DELETE /{name}`` yields a clean 404 when the macro is absent."""
    resp = router_client.delete("/api/v1/modules/macros/ghost")
    assert resp.status_code == 404
    body = resp.json()
    assert "detail" in body
    assert "ghost" in body["detail"]


# ---------------------------------------------------------------------- #
# PluggableModule contract / registry boot regression tests                #
# ---------------------------------------------------------------------- #


def test_macros_module_satisfies_pluggable_protocol() -> None:
    """``isinstance(MacrosModule(), PluggableModule)`` must be ``True``.

    ``PluggableModule`` is ``@runtime_checkable`` and inspects every
    declared member, so omitting ``get_settings_model`` would cause
    the registry's :meth:`ModuleRegistry.discover` to silently skip
    the macros module. This test pins the contract so a future
    refactor that drops the method fails fast.
    """
    from backend.modules.macros import setup as macros_setup
    from core.protocols import PluggableModule

    instance = macros_setup()
    assert isinstance(instance, PluggableModule)
    # All declared members must be present and callable where applicable.
    assert hasattr(instance, "manifest")
    assert callable(getattr(instance, "on_load"))
    assert callable(getattr(instance, "on_unload"))
    assert callable(getattr(instance, "get_router"))
    assert callable(getattr(instance, "get_settings_model"))


def test_macros_module_boots_and_registers_router(
    tmp_data_root, clean_env
) -> None:
    """Booting the registry mounts the macros router + settings endpoints.

    End-to-end check that the module is discoverable, that the
    registry mounts its router under ``/api/v1/modules/macros``,
    and that the canonical settings endpoints are reachable.

    The test only exercises *read-only* endpoints so the real
    ``./macros/`` storage directory (the module's default) is never
    mutated; CRUD round-trips against an isolated ``tmp_path``
    fixture are covered by the router tests above.
    """
    from backend.modules.macros import setup as macros_setup
    from core.module_registry import ModuleRegistry

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, candidates=[macros_setup()])

    assert "macros" in reg.modules
    assert reg.manifests["macros"].id == "macros"
    assert reg.manifests["macros"].settings_panel is False

    client = TestClient(app)

    # Canonical settings endpoints (mounted by the registry).
    resp = client.get("/api/v1/modules/macros/settings")
    assert resp.status_code == 200
    assert resp.json() == {}

    # The macros router is mounted at /api/v1/modules/macros.
    # ``GET /`` is a non-mutating list endpoint, safe to call even
    # when the module's default storage directory already exists
    # on the test host.
    resp = client.get("/api/v1/modules/macros/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # 404 surface (``read`` of a missing file maps to ``MacroNotFoundError``).
    resp = client.get("/api/v1/modules/macros/does_not_exist")
    assert resp.status_code == 404

    # 400 surface for a name with a non-``.macro`` suffix.
    resp = client.put(
        "/api/v1/modules/macros/bad.txt",
        json={"content": "x"},
    )
    assert resp.status_code == 400