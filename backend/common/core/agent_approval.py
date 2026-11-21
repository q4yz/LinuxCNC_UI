"""Proof that the operator approved one exact agent request.

When the operator approves an agent action (``services.AgentConfirmationService``
on the system backend), the MCP server sends the request with an
``X-Agent-Approval`` header: an id, an expiry, and an HMAC — keyed with
the agent token both backends know — over the request's method, path,
query string and body bytes. :func:`core.auth.make_authorize` lets the
agent through a ``confirm`` route only with a valid, unexpired, unused
approval for *that* request: another path, other arguments or a second
use are refused.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time

from core.agent_token import agent_token

HEADER = "X-Agent-Approval"
#: How long an approval may wait before its request is sent (s).
VALIDITY = 30.0


def _message(approval_id: str, expires: int, method: str, raw_path: bytes, query: bytes, body: bytes) -> bytes:
    return b"\n".join(
        [approval_id.encode(), str(expires).encode(), method.upper().encode(), raw_path, query, hashlib.sha256(body).hexdigest().encode()]
    )


def sign(method: str, raw_path: bytes, query: bytes, body: bytes, *, approval_id: str | None = None, now: float | None = None) -> str:
    """The header value approving one request."""
    approval_id = approval_id or secrets.token_hex(8)
    expires = int((now if now is not None else time.time()) + VALIDITY)
    mac = hmac.new(agent_token().encode(), _message(approval_id, expires, method, raw_path, query, body), hashlib.sha256)
    return f"{approval_id}.{expires}.{mac.hexdigest()}"


class _UsedApprovals:
    """Approval ids already spent in this process (until they expire)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._used: dict[str, int] = {}

    def spend(self, approval_id: str, expires: int, now: float) -> bool:
        with self._lock:
            for key in [k for k, exp in self._used.items() if exp < now]:
                del self._used[key]
            if approval_id in self._used:
                return False
            self._used[approval_id] = expires
            return True


_used = _UsedApprovals()


def verify(header: str, method: str, raw_path: bytes, query: bytes, body: bytes, *, now: float | None = None) -> bool:
    """``header`` approves exactly this request, now, for the first time."""
    now = now if now is not None else time.time()
    try:
        approval_id, expires_text, mac = header.strip().split(".")
        expires = int(expires_text)
    except ValueError:
        return False
    if not approval_id or expires < now or expires > now + VALIDITY + 5:
        return False
    expected = hmac.new(agent_token().encode(), _message(approval_id, expires, method, raw_path, query, body), hashlib.sha256)
    if not hmac.compare_digest(expected.hexdigest(), mac):
        return False
    return _used.spend(approval_id, expires, now)


__all__ = ["HEADER", "VALIDITY", "sign", "verify"]
