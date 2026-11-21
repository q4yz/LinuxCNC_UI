"""The caller and the permission check every route runs.

:func:`authorize` is an app-wide dependency of both backends: it finds
the route's permission in :mod:`core.permissions` and refuses the call
(403) unless the caller's role allows it. ``CONFIRM`` is refused too
until the operator-confirmation flow exists; no current role uses it.

There are no logins yet: :func:`current_user` returns the local admin
for every request, except the MCP server's calls for the agent (the
agent token). Logins replace that function only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, NoReturn

from fastapi import HTTPException, WebSocketException, status
from starlette.requests import HTTPConnection

from core.permissions import PUBLIC_PATHS, Level, Permission, level


@dataclass(frozen=True, slots=True)
class User:
    name: str
    role: str


#: Every caller, until there are logins.
LOCAL_ADMIN = User(name="local", role="admin")
#: The assistant, calling through the MCP server (``core.agent_token``).
AGENT = User(name="agent", role="agent")


def current_user(connection: HTTPConnection) -> User:
    """Who is calling: the agent when it presents the agent token,
    otherwise (no logins yet) the local admin."""
    scheme, _, token = connection.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token:
        from core.agent_token import is_agent_token

        if is_agent_token(token.strip()):
            return AGENT
    return LOCAL_ADMIN


def route_key(connection: HTTPConnection) -> tuple[str, str] | None:
    """``(method, path template)`` of the matched route (``WS`` for a
    WebSocket), or ``None`` before routing."""
    route = connection.scope.get("route")
    path = getattr(route, "path", None)
    if path is None:
        return None
    method = "WS" if connection.scope.get("type") == "websocket" else str(connection.scope.get("method", "GET")).upper()
    return method, path


def make_authorize(routes: Mapping[tuple[str, str], Permission]) -> Callable[[HTTPConnection], User]:
    """The dependency for one backend's route table."""

    def authorize(connection: HTTPConnection) -> User:
        user = current_user(connection)
        key = route_key(connection)
        if key is None or key[1] in PUBLIC_PATHS:
            return user
        permission = routes.get(key)
        if permission is None:
            # A route nobody gave a permission: only admin (fail closed).
            if user.role == "admin":
                return user
            _refuse(connection, f"{key[0]} {key[1]} has no permission assigned")
        granted = level(user.role, permission)
        if granted is Level.ALLOW:
            return user
        detail = (
            f"'{permission.value}' needs the operator's confirmation"
            if granted is Level.CONFIRM
            else f"role '{user.role}' may not '{permission.value}'"
        )
        _refuse(connection, detail)

    return authorize


def _refuse(connection: HTTPConnection, detail: str) -> NoReturn:
    if connection.scope.get("type") == "websocket":
        raise WebSocketException(status.WS_1008_POLICY_VIOLATION, detail)
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail)


def annotate_openapi(app: object, routes: Mapping[tuple[str, str], Permission]) -> None:
    """Put each operation's permission and the agent's level into the
    OpenAPI schema (``x-permission``, ``x-agent``) — what the MCP layer
    filters on. Call after every route is added."""
    from fastapi.routing import APIRoute

    for route in getattr(app, "routes", []):
        if not isinstance(route, APIRoute):
            continue
        extra: dict[str, object] = {}
        for method in route.methods:
            permission = routes.get((method, route.path))
            if permission is not None:
                extra = {"x-permission": permission.value, "x-agent": level("agent", permission).value}
        if extra:
            route.openapi_extra = {**(route.openapi_extra or {}), **extra}


__all__ = ["AGENT", "LOCAL_ADMIN", "User", "annotate_openapi", "current_user", "make_authorize", "route_key"]
