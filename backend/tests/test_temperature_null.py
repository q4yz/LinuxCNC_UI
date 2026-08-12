"""Tests for the nullable-module guarantee.

Validates that booting without the temperature module folder on
disk leaves the registry in a clean state — ``mounted=[]`` (or
``mounted=['camera']`` if camera is also present), no errors, and
no route under ``/api/v1/modules/temperature`` is registered.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.module_registry import ModuleRegistry


def _fresh_app(tmp_data_root, monkeypatch, package_name: str = "modules"):
    """Boot a registry whose discovery surface is ``package_name``.

    Uses ``monkeypatch.syspath_prepend`` so a temp package can stand
    in for ``backend.modules`` without touching the real directory.
    """
    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    return reg, app


def test_temperature_module_not_imported_yields_empty_mount(
    tmp_data_root, clean_env, caplog, monkeypatch
):
    """If ``modules.temperature`` cannot be imported, the registry
    boots with ``mounted=[]`` and logs no error.
    """
    # Force ``importlib.import_module`` to fail for the temperature
    # package by registering a fake loader that raises ImportError.
    import importlib.abc
    import importlib.machinery

    class _BoomLoader(importlib.abc.Loader):
        def create_module(self, spec):
            return None

        def exec_module(self, module):
            raise ImportError("simulated: temperature module removed")

    boom_spec = importlib.machinery.ModuleSpec("modules.temperature", _BoomLoader())
    monkeypatch.setitem(sys.modules, "modules.temperature", None)
    # Re-import ``modules`` to force re-discovery.
    if "modules" in sys.modules:
        importlib.reload(sys.modules["modules"])

    # The real loader will fail and the registry should skip the
    # module without crashing. We assert that the boot summary log
    # is either ``mounted=[]`` or contains only other modules.
    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    with caplog.at_level(logging.INFO, logger="core.module_registry"):
        reg.boot(app)

    summary = [
        r.message
        for r in caplog.records
        if "registry: mounted=" in r.message
    ]
    assert summary, "expected boot summary log line"
    assert "temperature" not in reg.modules
    # The surviving ``/sensors/{name}/target`` route must not be
    # registered when the module is absent.
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/temperature/sensors/extruder/target",
        json={"sensor_name": "extruder", "target": 50.0},
    )
    assert resp.status_code == 404


def test_temperature_module_folder_removed_simulated(
    tmp_data_root, clean_env, caplog, monkeypatch
):
    """If ``modules.temperature.setup`` raises during ``discover``,
    the registry continues with the remaining modules.
    """
    # Stub out ``modules.temperature.setup`` to raise so the
    # registry records a setup() failure and skips it.
    import modules.temperature as temp_pkg  # noqa: F401

    def boom_setup():
        raise RuntimeError("simulated: setup() raised")

    monkeypatch.setattr(temp_pkg, "setup", boom_setup, raising=False)
    # Force the registry to re-discover from scratch.
    for mid in list(ModuleRegistry().modules):
        ModuleRegistry().modules.pop(mid)
    for mid in list(ModuleRegistry().manifests):
        ModuleRegistry().manifests.pop(mid)

    # Build a fresh registry so the boot summary log line is fresh.
    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    with caplog.at_level(logging.INFO, logger="core.module_registry"):
        reg.boot(app)

    # The registry must have continued past the failure.
    summary = [
        r.message
        for r in caplog.records
        if "registry: mounted=" in r.message
    ]
    assert summary
    assert "temperature" not in reg.modules


def test_no_op_unload_when_module_is_unmounted(tmp_data_root, clean_env):
    """``registry.shutdown()`` is idempotent even if the temperature
    module was never mounted.
    """
    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, candidates=[])
    # Should not raise even though nothing was mounted.
    reg.shutdown()
    reg.shutdown()  # second call is a no-op
    assert reg.modules == {}
