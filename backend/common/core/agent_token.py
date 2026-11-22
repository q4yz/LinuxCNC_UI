"""The agent's credential: a random token both backends know.

The MCP server sends it as ``Authorization: Bearer <token>`` on every
call it makes for the agent; :func:`core.auth.current_user` then gives
that call the ``agent`` role, so the backends' own permission check is
what limits the agent. Created on first use (``backend/data/agent.token``,
readable by the owner only); ``LINUXCNC_UI_AGENT_TOKEN`` overrides it.
"""
from __future__ import annotations

import hmac
import os
import secrets
from functools import lru_cache
from pathlib import Path

ENV = "LINUXCNC_UI_AGENT_TOKEN"
TOKEN_FILE = Path(__file__).resolve().parents[2] / "data" / "agent.token"


@lru_cache(maxsize=1)
def agent_token() -> str:
    from_env = os.environ.get(ENV, "").strip()
    if from_env:
        return from_env
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create: two backends starting together agree on one token.
    try:
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token)
    return token


def is_agent_token(presented: str) -> bool:
    return bool(presented) and hmac.compare_digest(presented.encode(), agent_token().encode())


__all__ = ["ENV", "TOKEN_FILE", "agent_token", "is_agent_token"]
