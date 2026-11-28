"""A failed M-code helper shows up in the UI console."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.state as state


def test_reports_land_in_the_console(monkeypatch):
    logged = []

    class Console:
        def log_event(self, text, level=None, source=None):
            logged.append((text, level, source))

    monkeypatch.setattr(state, "get_console_logger", lambda: Console())
    app = FastAPI()
    app.include_router(state.router)
    response = TestClient(app).post(
        "/api/v1/modules/machine_state/mcode_error",
        json={"code": "m106", "message": "this machine has no part fan 0"},
    )
    assert response.status_code == 200
    text, level, source = logged[0]
    assert text.startswith("M106 failed: this machine has no part fan 0")
    assert level == state.LogLevel.ERROR and source == "CMD"
