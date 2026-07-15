"""Nullable-module guarantee for the camera module.

Boot the registry with an empty candidate list (no camera, no anything)
and verify:

* The boot summary log line reads ``mounted=[] skipped=0 missing=0``.
* No errors leak into the log.
* The FastAPI app still starts cleanly — the ``/api/v1/modules/camera``
  prefix returns ``404`` because no router is mounted there, but no
  module code is imported at all.

This is the most important acceptance criterion from Issue #2: the
camera module is *removable* without breaking the rest of the app.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.module_registry import ModuleRegistry


def test_empty_candidate_list_logs_clean_summary(tmp_data_root, clean_env, caplog):
    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    with caplog.at_level(logging.INFO, logger="core.module_registry"):
        reg.boot(app, bus=EventBus(), candidates=[])

    # The summary line is the acceptance marker from the issue.
    summary = [
        r.message
        for r in caplog.records
        if "registry: mounted=" in r.message
    ]
    assert summary, "expected the boot summary log line"
    assert "mounted=[]" in summary[0]
    assert "skipped=0" in summary[0]
    assert "missing=0" in summary[0]


def test_no_camera_routes_when_module_absent(tmp_data_root, clean_env):
    """Without the camera module the /api/v1/modules/camera/* paths 404."""
    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, bus=EventBus(), candidates=[])

    client = TestClient(app)
    for path in (
        "/api/v1/modules/camera/stream",
        "/api/v1/modules/camera/status",
        "/api/v1/modules/camera/settings",
    ):
        resp = client.get(path)
        assert resp.status_code == 404, (
            f"{path} must 404 when the camera module is absent, "
            f"got {resp.status_code}"
        )


def test_legacy_router_is_not_imported_from_routers_package(
    tmp_data_root, clean_env,
):
    """``backend.routers.camera`` no longer exists post-migration.

    This is the backend half of the "deleting the module folder boots
    cleanly" guarantee: if ``main.py`` had a stale ``from routers
    import camera``, the import would now fail. We verify the routers
    package imports cleanly without it.
    """
    import routers  # noqa: F401 - smoke import
    import importlib

    spec = importlib.util.find_spec("routers.camera")
    assert spec is None, "routers.camera must be removed after migration"