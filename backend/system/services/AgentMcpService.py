"""The MCP server for the assistant (``/mcp`` on the system backend).

Its tools are the backends' OpenAPI operations
(:mod:`core.openapi_tools`), read from each backend's live
``/openapi.json`` — no tool is defined here. A backend that is down
(the machine backend while LinuxCNC is stopped) simply contributes no
tools until it is back.

Every call goes to the REST API with the agent token
(:mod:`core.agent_token`), so the backend treats it as the ``agent``
role and its permission check decides — whoever connects to ``/mcp``
gets the agent's rights, never more. Operations the agent may only use
after the operator confirms (``x-agent: confirm``) are not offered
until that confirmation flow exists (:data:`OFFER_CONFIRM`).

Transport: MCP Streamable HTTP, stateless, JSON responses.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from typing import Any, AsyncIterator, Mapping

import httpx
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Receive, Scope, Send

from core.agent_token import agent_token
from core.openapi_tools import AgentTool, build_request, tools_from_openapi

logger = logging.getLogger("backend.system.mcp")

#: Offer the ``confirm`` operations (needs the operator-confirmation flow).
OFFER_CONFIRM = False
#: How long a backend's tool list is reused before re-reading its schema (s).
CATALOG_TTL = 5.0
#: Longest tool result handed to the agent (characters).
MAX_RESULT = 60_000

DEFAULT_BACKENDS = {
    "machine": os.environ.get("LINUXCNC_UI_MACHINE_URL", "http://127.0.0.1:8000"),
    "system": os.environ.get("LINUXCNC_UI_SYSTEM_URL", "http://127.0.0.1:8001"),
}

INSTRUCTIONS = (
    "Tools for a LinuxCNC machine (a CNC mill or a 3D printer) run through LinuxCNC UI. "
    "machine_* tools talk to the running machine (state, positions, temperatures, I/O, "
    "calibrations); system_* tools to the always-on system service (programs, profiles, "
    "macros, settings, versions). You act with the 'agent' role: you may read everything and "
    "engage the E-stop; actions that move, heat or change the machine need the operator's "
    "confirmation and are not available yet. Machine tools are missing while LinuxCNC is stopped."
)


class ToolCatalog:
    """The agent's tools, read from the backends' OpenAPI documents."""

    def __init__(
        self,
        clients: Mapping[str, httpx.AsyncClient],
        *,
        ttl: float = CATALOG_TTL,
        offer_confirm: bool = OFFER_CONFIRM,
    ) -> None:
        self._clients = dict(clients)
        self._ttl = ttl
        self._offer_confirm = offer_confirm
        self._cache: dict[str, tuple[float, list[AgentTool]]] = {}

    async def _backend_tools(self, backend: str) -> list[AgentTool]:
        cached = self._cache.get(backend)
        if cached and time.monotonic() - cached[0] < self._ttl:
            return cached[1]
        try:
            response = await self._clients[backend].get("/openapi.json", timeout=5.0)
            response.raise_for_status()
            tools = tools_from_openapi(backend, response.json(), offer_confirm=self._offer_confirm)
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("MCP: %s backend unavailable (%s); its tools are left out", backend, exc)
            tools = []
        self._cache[backend] = (time.monotonic(), tools)
        return tools

    async def tools(self) -> dict[str, AgentTool]:
        out: dict[str, AgentTool] = {}
        for backend in self._clients:
            for tool in await self._backend_tools(backend):
                out[tool.name] = tool
        return out

    async def call(self, name: str, arguments: Mapping[str, Any] | None) -> types.CallToolResult:
        tool = (await self.tools()).get(name)
        if tool is None:
            return _error(f"Unknown tool '{name}' (or its backend is not running).")
        try:
            request = build_request(tool, arguments)
        except ValueError as exc:
            return _error(str(exc))
        headers = {"Authorization": f"Bearer {agent_token()}"}
        if request.text is not None:
            headers["Content-Type"] = "text/plain"
        try:
            response = await self._clients[tool.backend].request(
                request.method,
                request.path,
                params=request.params,
                json=request.json if request.text is None and request.json is not None else None,
                content=request.text,
                headers=headers,
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            return _error(f"The {tool.backend} backend did not answer: {exc}")
        logger.info("MCP agent call: %s %s -> %s", request.method, request.path, response.status_code)
        return _result(response)


def _error(text: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=True)


def _result(response: httpx.Response) -> types.CallToolResult:
    text = response.text
    structured: dict[str, Any] | None = None
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            structured = parsed
        text = json.dumps(parsed, ensure_ascii=False)
    except ValueError:
        pass
    if len(text) > MAX_RESULT:
        text, structured = text[:MAX_RESULT] + "\n[truncated]", None
    if response.status_code >= 400:
        text = f"HTTP {response.status_code}: {text}"
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text or f"HTTP {response.status_code}")],
        structured_content=structured,
        is_error=response.status_code >= 400,
    )


def _mcp_tool(tool: AgentTool) -> types.Tool:
    return types.Tool(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
        annotations=types.ToolAnnotations(
            read_only_hint=tool.read_only,
            destructive_hint=tool.method == "DELETE",
            idempotent_hint=tool.method in ("GET", "PUT", "DELETE"),
            open_world_hint=False,
        ),
    )


def build_server(catalog: ToolCatalog) -> Server[Any]:
    async def list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[_mcp_tool(t) for t in (await catalog.tools()).values()])

    async def call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        return await catalog.call(params.name, params.arguments)

    return Server(
        "linuxcnc-ui",
        version="1.0.0",
        title="LinuxCNC UI",
        instructions=INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


class McpEndpoint:
    """The ASGI app behind ``/mcp``; :meth:`run` (in the app's lifespan)
    starts a fresh session manager, so the app can start more than once
    (tests)."""

    def __init__(self, backends: Mapping[str, str] | None = None, clients: Mapping[str, httpx.AsyncClient] | None = None):
        self._backends = dict(backends or DEFAULT_BACKENDS)
        self._clients = clients
        self._manager: StreamableHTTPSessionManager | None = None

    @contextlib.asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        async with contextlib.AsyncExitStack() as stack:
            clients = self._clients or {
                name: await stack.enter_async_context(httpx.AsyncClient(base_url=url)) for name, url in self._backends.items()
            }
            manager = StreamableHTTPSessionManager(app=build_server(ToolCatalog(clients)), stateless=True, json_response=True)
            await stack.enter_async_context(manager.run())
            self._manager = manager
            try:
                yield
            finally:
                self._manager = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._manager is None:
            body = b'{"detail":"MCP server not running"}'
            await send({"type": "http.response.start", "status": 503, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
            return
        await self._manager.handle_request(scope, receive, send)


mcp_endpoint = McpEndpoint()

__all__ = ["DEFAULT_BACKENDS", "McpEndpoint", "OFFER_CONFIRM", "ToolCatalog", "build_server", "mcp_endpoint"]
