"""The MCP server: tools from the backends' schemas, calls as the agent."""
from __future__ import annotations

import anyio
import httpx
import pytest
from fastapi import Depends, FastAPI
from mcp import Client

from core import agent_token as token_module
from core.auth import annotate_openapi, make_authorize
from core.permissions import Permission
from core.agent_approval import HEADER, sign
from services.AgentConfirmationService import AgentConfirmationService, Decision
from services.AgentMcpService import ToolCatalog, build_server

ROUTES = {
    ("GET", "/api/v1/state"): Permission.MACHINE_READ,
    ("POST", "/api/v1/estop"): Permission.MACHINE_ESTOP,
    ("POST", "/api/v1/mdi"): Permission.MACHINE_MOTION,
    ("POST", "/api/v1/update"): Permission.SYSTEM_UPDATE,
}


def _machine() -> FastAPI:
    app = FastAPI(dependencies=[Depends(make_authorize(ROUTES))])
    app.state.calls = []

    @app.get("/api/v1/state", summary="Read the state")
    def state(verbose: bool = False):
        return {"state": "on", "verbose": verbose}

    @app.post("/api/v1/estop", summary="Engage the E-stop")
    def estop():
        app.state.calls.append("estop")
        return {"ok": True}

    @app.post("/api/v1/mdi")
    def mdi():
        app.state.calls.append("mdi")
        return {"ok": True}

    @app.post("/api/v1/update")
    def update():
        app.state.calls.append("update")
        return {"ok": True}

    annotate_openapi(app, ROUTES)
    return app


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setenv(token_module.ENV, "test-token")
    token_module.agent_token.cache_clear()
    yield
    token_module.agent_token.cache_clear()


def _run(fn):
    return anyio.run(fn)


def _catalog(http, **kw):
    return ToolCatalog({"machine": http}, ttl=0, confirmations=kw.pop("confirmations", AgentConfirmationService(timeout=5)), **kw)


def test_tools_come_from_the_schema_and_calls_run_as_the_agent():
    app = _machine()

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://machine") as http:
            async with Client(build_server(_catalog(http))) as client:
                names = {t.name for t in (await client.list_tools()).tools}
                # update: deny, never offered; mdi: confirm, offered (waits for the operator)
                assert names == {"machine_get_state", "machine_post_estop", "machine_post_mdi"}
                result = await client.call_tool("machine_get_state", {"verbose": True})
                assert not result.is_error and result.structured_content == {"state": "on", "verbose": True}
                assert not (await client.call_tool("machine_post_estop", {})).is_error
                refused = await client.call_tool("machine_post_update", {})
                assert refused.is_error and "Unknown tool" in refused.content[0].text

    _run(go)
    assert app.state.calls == ["estop"]


async def _answer_when_asked(confirmations, approve, reason=""):
    for _ in range(200):
        pending = [c for c in confirmations.list() if c.decision is Decision.PENDING]
        if pending:
            return confirmations.answer(pending[0].id, approve, reason)
        await anyio.sleep(0.01)
    raise AssertionError("nothing was asked")


def test_an_approved_action_runs_once():
    app = _machine()
    confirmations = AgentConfirmationService(timeout=5)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://machine") as http:
            catalog = _catalog(http, confirmations=confirmations)
            async with anyio.create_task_group() as tg:
                tg.start_soon(_answer_when_asked, confirmations, True)
                result = await catalog.call("machine_post_mdi", {})
            assert not result.is_error, result.content[0].text
            asked = confirmations.list()[0]
            assert (asked.method, asked.path, asked.permission) == ("POST", "/api/v1/mdi", "machine.motion")

    _run(go)
    assert app.state.calls == ["mdi"]


def test_a_denied_action_does_not_run():
    app = _machine()
    confirmations = AgentConfirmationService(timeout=5)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://machine") as http:
            catalog = _catalog(http, confirmations=confirmations)
            async with anyio.create_task_group() as tg:
                tg.start_soon(_answer_when_asked, confirmations, False, "not now")
                result = await catalog.call("machine_post_mdi", {})
            assert result.is_error and "declined: not now" in result.content[0].text

    _run(go)
    assert app.state.calls == []


def test_an_unanswered_action_expires():
    app = _machine()

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://machine") as http:
            result = await _catalog(http, confirmations=AgentConfirmationService(timeout=0.05)).call("machine_post_mdi", {})
            assert result.is_error and "did not answer" in result.content[0].text

    _run(go)
    assert app.state.calls == []


def test_the_backend_wants_the_approval_for_exactly_that_request():
    app = _machine()

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://machine") as http:
            auth = {"Authorization": "Bearer test-token"}
            assert (await http.post("/api/v1/mdi", headers=auth)).status_code == 403  # no approval
            good = sign("POST", b"/api/v1/mdi", b"", b"")
            assert (await http.post("/api/v1/mdi", headers={**auth, HEADER: good})).status_code == 200
            assert (await http.post("/api/v1/mdi", headers={**auth, HEADER: good})).status_code == 403  # used
            other = sign("POST", b"/api/v1/estop", b"", b"")
            assert (await http.post("/api/v1/mdi", headers={**auth, HEADER: other})).status_code == 403  # other path
            body = sign("POST", b"/api/v1/mdi", b"", b'{"a":1}')
            assert (await http.post("/api/v1/mdi", headers={**auth, HEADER: body}, content=b'{"a":2}')).status_code == 403
            update = sign("POST", b"/api/v1/update", b"", b"")
            assert (await http.post("/api/v1/update", headers={**auth, HEADER: update})).status_code == 403  # deny stays deny
            old = sign("POST", b"/api/v1/mdi", b"", b"", now=0)
            assert (await http.post("/api/v1/mdi", headers={**auth, HEADER: old})).status_code == 403  # expired

    _run(go)
    assert app.state.calls == ["mdi"]


def test_the_agent_cannot_approve_itself():
    from core.permissions import SYSTEM_ROUTES, Level, level

    for key in [k for k in SYSTEM_ROUTES if k[1].startswith("/api/v1/agent/confirmations")]:
        assert level("agent", SYSTEM_ROUTES[key]) is Level.DENY
        assert level("operator", SYSTEM_ROUTES[key]) is Level.ALLOW


def test_a_backend_that_is_down_has_no_tools():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(refuse), base_url="http://machine") as http:
            assert await ToolCatalog({"machine": http}, ttl=0).tools() == {}

    _run(go)


def test_the_agent_token_marks_the_agent(monkeypatch):
    from starlette.requests import HTTPConnection

    from core.auth import AGENT, LOCAL_ADMIN, current_user

    def conn(header: str | None) -> HTTPConnection:
        headers = [(b"authorization", header.encode())] if header else []
        return HTTPConnection({"type": "http", "headers": headers})

    assert current_user(conn("Bearer test-token")) == AGENT
    assert current_user(conn("Bearer nope")) == LOCAL_ADMIN
    assert current_user(conn(None)) == LOCAL_ADMIN


def test_the_confirmation_routes():
    from fastapi.testclient import TestClient

    from routers import agent_confirmations
    from services import AgentConfirmationService as module

    service = AgentConfirmationService(timeout=5)
    app = FastAPI()
    app.include_router(agent_confirmations.router)
    original = module._service
    module._service = service
    try:
        client = TestClient(app)

        async def ask_and_answer():
            async with anyio.create_task_group() as tg:
                async def answer():
                    for _ in range(200):
                        items = client.get("/api/v1/agent/confirmations").json()["confirmations"]
                        if items:
                            assert items[0]["summary"] == "Run MDI" and items[0]["arguments"] == {"body": {"command": "G28"}}
                            r = client.post(f"/api/v1/agent/confirmations/{items[0]['id']}/deny", json={"reason": "busy"})
                            assert r.status_code == 200 and r.json()["decision"] == "denied"
                            again = client.post(f"/api/v1/agent/confirmations/{items[0]['id']}/approve")
                            assert again.status_code == 409
                            return
                        await anyio.sleep(0.01)

                tg.start_soon(answer)
                item = await service.request(tool="t", summary="Run MDI", method="POST", path="/x",
                                             arguments={"body": {"command": "G28"}}, permission="machine.motion")
                assert item.decision is Decision.DENIED and item.reason == "busy"

        anyio.run(ask_and_answer)
        assert client.post("/api/v1/agent/confirmations/nope/approve").status_code == 404
    finally:
        module._service = original


def test_the_operator_switch_turns_actions_off(monkeypatch):
    from services import AgentMcpService as mcp_module

    app = _machine()
    monkeypatch.setattr(mcp_module, "actions_allowed", lambda: False)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://machine") as http:
            catalog = ToolCatalog({"machine": http}, ttl=0, confirmations=AgentConfirmationService(timeout=5))
            assert set(await catalog.tools()) == {"machine_get_state", "machine_post_estop"}
            monkeypatch.setattr(mcp_module, "actions_allowed", lambda: True)
            assert "machine_post_mdi" in await catalog.tools()

    _run(go)


def test_actions_are_allowed_unless_switched_off(monkeypatch):
    from services import AgentMcpService as mcp_module
    from services import UiSettingsService

    class Store:
        def __init__(self, value):
            self.value = value

        def read(self, key):
            if self.value is KeyError:
                raise KeyError(key)
            return self.value

    for stored, expected in ((KeyError, True), (True, True), (False, False)):
        monkeypatch.setattr(UiSettingsService, "get_ui_settings_service", lambda s=Store(stored): s)
        assert mcp_module.actions_allowed() is expected
