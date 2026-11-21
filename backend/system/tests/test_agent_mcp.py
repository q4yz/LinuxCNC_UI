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


def test_tools_come_from_the_schema_and_calls_run_as_the_agent():
    app = _machine()

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://machine") as http:
            catalog = ToolCatalog({"machine": http}, ttl=0)
            async with Client(build_server(catalog)) as client:
                names = {t.name for t in (await client.list_tools()).tools}
                assert names == {"machine_get_state", "machine_post_estop"}  # mdi: confirm, update: deny
                result = await client.call_tool("machine_get_state", {"verbose": True})
                assert not result.is_error and result.structured_content == {"state": "on", "verbose": True}
                assert not (await client.call_tool("machine_post_estop", {})).is_error
                refused = await client.call_tool("machine_post_mdi", {})
                assert refused.is_error and "Unknown tool" in refused.content[0].text

    _run(go)
    assert app.state.calls == ["estop"]


def test_the_backend_refuses_the_agent_even_if_a_tool_were_offered():
    """Offering confirm tools does not bypass the backend's check."""
    app = _machine()

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://machine") as http:
            catalog = ToolCatalog({"machine": http}, ttl=0, offer_confirm=True)
            result = await catalog.call("machine_post_mdi", {})
            assert result.is_error and "403" in result.content[0].text and "confirmation" in result.content[0].text

    _run(go)
    assert app.state.calls == []


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
