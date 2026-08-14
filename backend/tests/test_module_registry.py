"""Tests for the ModuleRegistry discovery + whitelist + summary log."""

from __future__ import annotations

import logging
from typing import List

import pytest
from fastapi import FastAPI

from core.event_bus import EventBus
from core.module_registry import ModuleRegistry
from core.protocols import ModuleContext, ModuleManifest, PluggableModule, SidebarEntry


class _StubModule:
    """A minimal PluggableModule implementation used by these tests."""

    def __init__(self, mid: str, title: str, *, with_router: bool = False) -> None:
        self.manifest = ModuleManifest(
            id=mid,
            title=title,
            sidebar=SidebarEntry(id=mid, label=title),
        )
        self._with_router = with_router
        self.loaded = False
        self.unloaded = False
        self.context: ModuleContext | None = None

    def on_load(self, ctx: ModuleContext) -> None:
        self.loaded = True
        self.context = ctx

    def on_unload(self) -> None:
        self.unloaded = True

    def get_router(self):
        if not self._with_router:
            from fastapi import APIRouter

            # The contract requires a non-null router; the stub
            # returns an empty one when ``with_router=False`` so
            # tests that don't care about routing can still
            # satisfy the type check.
            return APIRouter()
        from fastapi import APIRouter

        router = APIRouter()

        @router.get("/ping", summary="Ping", description="Round-trip check")
        def ping():
            return {"ok": True, "module": self.manifest.id}

        return router

    def get_settings_model(self):
        from pydantic import BaseModel

        class _Empty(BaseModel):
            """Stub settings model — empty schema, just enough to
            satisfy the contract's non-null requirement."""

        # The contract requires a non-null Pydantic defaults
        # model; the stub returns an instance of a tiny subclass.
        return _Empty()


def _fresh_registry(tmp_data_root) -> ModuleRegistry:
    return ModuleRegistry(data_root=tmp_data_root)


def test_empty_candidate_list_yields_mounted_empty(
    tmp_data_root, clean_env, caplog
):
    """``mounted=[] skipped=0 missing=0`` when nothing is discovered."""
    reg = _fresh_registry(tmp_data_root)
    app = FastAPI()
    with caplog.at_level(logging.INFO, logger="core.module_registry"):
        reg.boot(app, candidates=[])
    assert reg.modules == {}
    assert reg.manifests == {}
    summary = [
        r.message
        for r in caplog.records
        if "registry: mounted=" in r.message
    ]
    assert summary, "expected the boot summary log line"
    assert "mounted=[]" in summary[0]
    assert "skipped=0" in summary[0]
    assert "missing=0" in summary[0]


def test_unknown_whitelist_entry_is_warned(
    tmp_data_root, monkeypatch, caplog
):
    """``MODULES_ENABLED=nonexistent`` logs ``WARN unknown module id``."""
    monkeypatch.setenv("MODULES_ENABLED", "nonexistent")
    reg = _fresh_registry(tmp_data_root)
    app = FastAPI()
    with caplog.at_level(logging.INFO, logger="core.module_registry"):
        reg.boot(app, candidates=[])
    warn_messages = [
        r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert any("unknown module id 'nonexistent'" in m for m in warn_messages)
    # And the summary line still reads ``mounted=[]``.
    summary = [
        r.getMessage() for r in caplog.records
        if "registry: mounted=" in r.getMessage()
    ]
    assert summary and "mounted=[]" in summary[0]


def test_whitelist_mounts_only_listed(
    tmp_data_root, monkeypatch, caplog
):
    """``MODULES_ENABLED=alpha`` mounts only alpha and skips beta."""
    monkeypatch.setenv("MODULES_ENABLED", "alpha")
    reg = _fresh_registry(tmp_data_root)
    app = FastAPI()
    alpha = _StubModule("alpha", "Alpha")
    beta = _StubModule("beta", "Beta")
    with caplog.at_level(logging.INFO, logger="core.module_registry"):
        reg.boot(app, candidates=[alpha, beta])
    assert set(reg.modules.keys()) == {"alpha"}
    summary = [
        r.message
        for r in caplog.records
        if "registry: mounted=" in r.message
    ]
    assert summary
    assert "mounted=['alpha']" in summary[0]
    assert "skipped=1" in summary[0]
    assert "missing=0" in summary[0]
    # Beta was never loaded; alpha was.
    assert not beta.loaded
    assert alpha.loaded


def test_shutdown_calls_on_unload_in_reverse_order(
    tmp_data_root, clean_env
):
    reg = _fresh_registry(tmp_data_root)
    app = FastAPI()
    a = _StubModule("a", "A")
    b = _StubModule("b", "B")
    c = _StubModule("c", "C")
    reg.boot(app, candidates=[a, b, c])
    order: List[str] = []
    for stub in (a, b, c):
        original = stub.on_unload

        def make_on_unload(s, original=original):
            def hook():
                order.append(s.manifest.id)
                original()

            return hook

        stub.on_unload = make_on_unload(stub)  # type: ignore[assignment]

    reg.shutdown()
    assert order == ["c", "b", "a"]


def test_routers_mounted_under_modules_prefix(tmp_data_root, clean_env):
    """Modules that return a router get it mounted under /api/v1/modules/<id>."""
    from fastapi.testclient import TestClient

    reg = _fresh_registry(tmp_data_root)
    app = FastAPI()
    alpha = _StubModule("alpha", "Alpha", with_router=True)
    reg.boot(app, candidates=[alpha])

    client = TestClient(app)
    resp = client.get("/api/v1/modules/alpha/ping")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "module": "alpha"}


def test_settings_router_mounted_under_modules_id_settings(
    tmp_data_root, clean_env
):
    """The four settings endpoints are always mounted per module."""
    from fastapi.testclient import TestClient

    reg = _fresh_registry(tmp_data_root)
    app = FastAPI()
    alpha = _StubModule("alpha", "Alpha")
    reg.boot(app, candidates=[alpha])

    client = TestClient(app)
    # Default GET returns an empty dict (no defaults set on this stub).
    r = client.get("/api/v1/modules/alpha/settings")
    assert r.status_code == 200
    assert r.json() == {}

    # PUT writes the payload.
    r = client.put("/api/v1/modules/alpha/settings", json={"k": 1})
    assert r.status_code == 200
    assert r.json() == {"k": 1}

    # GET round-trips.
    r = client.get("/api/v1/modules/alpha/settings")
    assert r.json() == {"k": 1}

    # Single-key GET.
    r = client.get("/api/v1/modules/alpha/settings/k")
    assert r.json() == {"k": 1}

    # Single-key PUT.
    r = client.put("/api/v1/modules/alpha/settings/k2", json=2)
    assert r.json() == {"k": 1, "k2": 2}


def test_missing_modules_package_does_not_explode(
    tmp_data_root, clean_env, caplog
):
    """A bad package name logs a warning and boots cleanly with empty list."""
    reg = _fresh_registry(tmp_data_root)
    app = FastAPI()
    with caplog.at_level(logging.WARNING, logger="core.module_registry"):
        discovered = reg.discover("does_not_exist_pkg_xyz")
    assert discovered == []
    # ``boot`` with no candidates is also clean.
    reg.boot(app, candidates=[])
    assert reg.modules == {}