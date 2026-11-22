"""OpenAPI operations -> agent tools. The schema is the only source.

Nothing here lists tools by hand: every tool is one operation of a
backend's live OpenAPI document, and everything about it comes from
that document:

* **whether** the agent gets it: ``x-agent`` (from the route's
  permission, :mod:`core.permissions`): ``allow`` yes, ``confirm`` only
  once operator confirmation exists, ``deny`` never; ``x-mcp: false``
  (a schema-only route), ``deprecated``, and operations that neither
  take nor return JSON / text (an upload form, a video stream) are left
  out;
* **name**: the method and path (``post_program_run``);
* **description**: the summary and description;
* **arguments**: the path and query parameters and the request body,
  as a JSON schema with the referenced component schemas inlined.

A call goes back through the REST API (:func:`build_request`), so the
backend's permission check, validation and error handling apply as
for any other caller.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import quote

#: Request / response bodies a tool can carry as text.
TEXT_TYPES = ("application/json", "text/plain")
#: Longest tool name (MCP clients commonly limit names to 64 characters).
MAX_NAME = 64
_STRIP = ("/api/v1/modules/", "/api/v1/")


@dataclass(frozen=True)
class AgentTool:
    backend: str
    name: str
    method: str
    path: str
    summary: str
    description: str
    input_schema: dict[str, Any]
    permission: str
    level: str
    path_params: tuple[str, ...] = ()
    query_params: tuple[str, ...] = ()
    body_type: str | None = None
    #: Path parameters that may contain ``/`` (``{filename:path}``).
    slash_params: frozenset[str] = field(default_factory=frozenset)

    @property
    def read_only(self) -> bool:
        return self.method == "GET"


def tool_name(backend: str, method: str, path: str) -> str:
    """``machine`` + ``POST /api/v1/modules/program/run`` -> ``machine_post_program_run``."""
    rest = path
    for prefix in _STRIP:
        if rest.startswith(prefix):
            rest = rest[len(prefix):]
            break
    words = re.sub(r"[^A-Za-z0-9]+", "_", re.sub(r"\{(\w+)(?::\w+)?\}", r"\1", rest)).strip("_").lower()
    name = f"{backend}_{method.lower()}" + (f"_{words}" if words else "_root")
    return name[:MAX_NAME].rstrip("_")


def _text_type(content: Mapping[str, Any] | None) -> str | None:
    for media in TEXT_TYPES:
        if content and media in content:
            return media
    return None


def _returns_text(operation: Mapping[str, Any]) -> bool:
    for code, response in (operation.get("responses") or {}).items():
        if str(code).startswith("2"):
            content = response.get("content")
            if content is None or _text_type(content):  # no body (204) is fine
                return True
    return False


def _collect_defs(node: Any, components: Mapping[str, Any], out: dict[str, Any]) -> Any:
    """``node`` with ``#/components/schemas/X`` refs rewritten to
    ``#/$defs/X``; every referenced schema copied into ``out``."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            name = ref.rsplit("/", 1)[1]
            if name not in out and name in components:
                out[name] = {}  # placeholder: breaks reference cycles
                out[name] = _collect_defs(components[name], components, out)
            return {**{k: v for k, v in node.items() if k != "$ref"}, "$ref": f"#/$defs/{name}"}
        return {k: _collect_defs(v, components, out) for k, v in node.items()}
    if isinstance(node, list):
        return [_collect_defs(v, components, out) for v in node]
    return node


def _description(operation: Mapping[str, Any], permission: str, level: str) -> str:
    parts = [str(operation.get("summary") or "").strip(), str(operation.get("description") or "").strip()]
    text = "\n\n".join(p for p in parts if p)
    return f"{text}\n\n(permission: {permission}; agent: {level})".strip()


def tools_from_openapi(backend: str, schema: Mapping[str, Any], *, offer_confirm: bool = False) -> list[AgentTool]:
    """The agent's tools for one backend's OpenAPI document."""
    components = (schema.get("components") or {}).get("schemas") or {}
    tools: list[AgentTool] = []
    for path, operations in (schema.get("paths") or {}).items():
        for method, operation in operations.items():
            if not isinstance(operation, dict) or method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue
            level = operation.get("x-agent")
            if level == "allow" or (level == "confirm" and offer_confirm):
                pass
            else:
                continue
            if operation.get("x-mcp") is False or operation.get("deprecated"):
                continue
            body = operation.get("requestBody")
            body_type = _text_type((body or {}).get("content")) if body else None
            if (body and body_type is None) or not _returns_text(operation):
                continue
            tools.append(_tool(backend, method.upper(), path, operation, components, body_type))
    return tools


def _tool(
    backend: str, method: str, path: str, operation: Mapping[str, Any], components: Mapping[str, Any], body_type: str | None
) -> AgentTool:
    defs: dict[str, Any] = {}
    properties: dict[str, Any] = {}
    required: list[str] = []
    path_params: list[str] = []
    query_params: list[str] = []
    for param in operation.get("parameters") or []:
        where, name = param.get("in"), param.get("name")
        if where not in ("path", "query") or not name:
            continue
        prop = dict(_collect_defs(param.get("schema") or {}, components, defs))
        if param.get("description") and "description" not in prop:
            prop["description"] = param["description"]
        properties[name] = prop
        (path_params if where == "path" else query_params).append(name)
        if param.get("required") or where == "path":
            required.append(name)
    if body_type is not None:
        body = operation["requestBody"]
        body_schema = (body["content"][body_type] or {}).get("schema") or {}
        prop = dict(_collect_defs(body_schema, components, defs))
        prop.setdefault("description", "The request body" + (" (text)" if body_type == "text/plain" else ""))
        properties["body"] = prop
        if body.get("required"):
            required.append("body")
    input_schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        input_schema["required"] = required
    if defs:
        input_schema["$defs"] = defs
    permission, level = str(operation.get("x-permission", "")), str(operation.get("x-agent", ""))
    return AgentTool(
        backend=backend,
        name=tool_name(backend, method, path),
        method=method,
        path=path,
        summary=str(operation.get("summary") or f"{method} {path}"),
        description=_description(operation, permission, level),
        input_schema=input_schema,
        permission=permission,
        level=level,
        path_params=tuple(path_params),
        query_params=tuple(query_params),
        body_type=body_type,
        slash_params=frozenset(re.findall(r"\{(\w+):path\}", path)),
    )


@dataclass(frozen=True)
class ToolRequest:
    method: str
    path: str
    params: dict[str, Any]
    json: Any = None
    text: str | None = None


def build_request(tool: AgentTool, arguments: Mapping[str, Any] | None) -> ToolRequest:
    """The REST call for a tool call. Raises ``ValueError`` on a missing
    path parameter."""
    args = dict(arguments or {})
    path = tool.path
    for name in tool.path_params:
        if name not in args:
            raise ValueError(f"missing argument '{name}'")
        value = quote(str(args[name]), safe="/" if name in tool.slash_params else "")
        path = re.sub(r"\{" + re.escape(name) + r"(?::\w+)?\}", lambda _m: value, path)
    params = {k: args[k] for k in tool.query_params if k in args and args[k] is not None}
    body = args.get("body")
    if tool.body_type == "text/plain":
        return ToolRequest(tool.method, path, params, text=None if body is None else str(body))
    return ToolRequest(tool.method, path, params, json=body)


__all__ = ["AgentTool", "ToolRequest", "build_request", "tool_name", "tools_from_openapi"]
