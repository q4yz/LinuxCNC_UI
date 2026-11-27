"""The caller and the permission check every route runs.

:func:`authorize` is an app-wide dependency of both backends: it finds
the route's permission in :mod:`core.permissions` and refuses the call
(403) unless the caller's role allows it. A ``CONFIRM`` permission
(the agent's machine actions) passes only with the operator's approval
of that exact request (:mod:`core.agent_approval`).

Who calls (:func:`current_user`, #131): the agent with the agent
token; an account with its session token (:mod:`core.session_token`,
accounts in :mod:`core.users_db`, which starts with the default admin
``remora`` / ``remora``); anyone else is a viewer.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Awaitable, Callable, Mapping, NoReturn

from fastapi import HTTPException, WebSocketException, status
from starlette.requests import HTTPConnection, Request

from core.permissions import PUBLIC_PATHS, Level, Permission, level


@dataclass(frozen=True, slots=True)
class User:
    name: str
    role: str


logger = logging.getLogger("core.auth")

#: An admin caller (tests, in-process callers).
LOCAL_ADMIN = User(name="local", role="admin")
#: The assistant, calling through the MCP server (``core.agent_token``).
AGENT = User(name="agent", role="agent")
#: Anyone without (a valid) login once accounts exist.
GUEST = User(name="guest", role="viewer")

#: WebSockets cannot send headers from a browser: the token comes as a
#: query parameter there (only there — URLs end up in logs).
WS_TOKEN_PARAM = "access_token"


def presented_token(connection: HTTPConnection) -> str:
    """The credential the caller sent: ``Authorization: Bearer``, the
    ``X-Api-Key`` header (slicers' OctoPrint upload), or on a WebSocket
    the ``access_token`` query parameter."""
    scheme, _, token = connection.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    api_key = connection.headers.get("x-api-key", "").strip()
    if api_key:
        return api_key
    if connection.scope.get("type") == "websocket":
        return connection.query_params.get(WS_TOKEN_PARAM, "").strip()
    return ""


def current_user(connection: HTTPConnection) -> User:
    """Who is calling: the agent (agent token), an account (session
    token), else a viewer."""
    from core.agent_token import is_agent_token
    from core.session_token import verify
    from core.users_db import get_user_store

    token = presented_token(connection)
    if token and is_agent_token(token):
        return AGENT
    store = get_user_store()
    try:
        account = verify(token, store) if token else None
    except sqlite3.Error as exc:
        logger.error("user database unreadable (%s): treating the caller as a viewer", exc)
        return GUEST
    return User(name=account.name, role=account.role) if account is not None else GUEST


def route_key(connection: HTTPConnection) -> tuple[str, str] | None:
    """``(method, path template)`` of the matched route (``WS`` for a
    WebSocket), or ``None`` before routing."""
    route = connection.scope.get("route")
    path = getattr(route, "path", None)
    if path is None:
        return None
    method = "WS" if connection.scope.get("type") == "websocket" else str(connection.scope.get("method", "GET")).upper()
    return method, path


def make_authorize(routes: Mapping[tuple[str, str], Permission]) -> Callable[[HTTPConnection], Awaitable[User]]:
    """The dependency for one backend's route table."""

    async def authorize(connection: HTTPConnection) -> User:
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
        if granted is Level.CONFIRM:
            if await _approved(connection):
                return user
            _refuse(connection, f"'{permission.value}' needs the operator's confirmation")
        _refuse(connection, f"role '{user.role}' may not '{permission.value}'")

    return authorize


async def _approved(connection: HTTPConnection) -> bool:
    """The request carries the operator's approval for exactly itself
    (:mod:`core.agent_approval`)."""
    from core.agent_approval import HEADER, verify

    header = connection.headers.get(HEADER)
    if not header or not isinstance(connection, Request):
        return False
    body = await connection.body()
    raw_path = (connection.scope.get("raw_path") or connection.scope.get("path", "").encode()).split(b"?", 1)[0]
    return verify(header, connection.method, raw_path, connection.scope.get("query_string", b""), body)


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


__all__ = ["AGENT", "GUEST", "LOCAL_ADMIN", "WS_TOKEN_PARAM", "User", "presented_token", "annotate_openapi", "current_user", "make_authorize", "route_key"]
