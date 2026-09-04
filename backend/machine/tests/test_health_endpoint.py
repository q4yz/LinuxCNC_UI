"""Functional pin for the machine-service health probe.

``GET /api/v1/health`` is the liveness route the frontend's
machine-online heartbeat polls
(``frontend/src/composables/useMachineOnline.ts``). It must live
under the ``/api`` proxy prefix — the browser cannot reach the
service root ``/`` through the dev/nginx proxy — and must answer
``{"status": "ok"}`` without touching hardware so a dead HAL never
masks a live HTTP server (or vice versa).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _main_source() -> str:
    # tests/ sits one level below the service root (backend/machine).
    root = Path(__file__).resolve().parent.parent
    return (root / "main.py").read_text(encoding="utf-8")


def test_health_route_is_declared_under_api_prefix():
    src = _main_source()
    assert '@app.get("/api/v1/health")' in src, (
        "health probe must be mounted at /api/v1/health "
        "so the /api dev+nginx proxy can route it"
    )


def test_health_endpoint_answers_ok():
    import main as machine_main

    # Plain TestClient (no context manager) → no lifespan/startup
    # side effects, just the route table.
    client = TestClient(machine_main.app)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
