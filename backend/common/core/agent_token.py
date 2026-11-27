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
from functools import lru_cache

from core.secret_file import DATA_DIR, read_or_create

ENV = "LINUXCNC_UI_AGENT_TOKEN"
TOKEN_FILE = DATA_DIR / "agent.token"


@lru_cache(maxsize=1)
def agent_token() -> str:
    from_env = os.environ.get(ENV, "").strip()
    if from_env:
        return from_env
    return read_or_create(TOKEN_FILE)


def is_agent_token(presented: str) -> bool:
    return bool(presented) and hmac.compare_digest(presented.encode(), agent_token().encode())


__all__ = ["ENV", "TOKEN_FILE", "agent_token", "is_agent_token"]
