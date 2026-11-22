"""The assistant's actions waiting for the operator.

The MCP server (:mod:`services.AgentMcpService`) puts each ``confirm``
tool call here and waits; the UI (the assistant panel) lists the
pending ones and approves or denies them through
``/api/v1/agent/confirmations``. Nothing is persisted: a restart
forgets pending requests, and the waiting tool calls end with them.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("backend.system.agent_confirmations")

#: How long a request waits for the operator (s).
TIMEOUT = 120.0
#: Decided requests kept in the list for the UI (s).
KEEP_DECIDED = 30.0


class Decision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass
class Confirmation:
    id: str
    tool: str
    summary: str
    method: str
    path: str
    arguments: dict[str, Any]
    permission: str
    created: float
    expires: float
    decision: Decision = Decision.PENDING
    decided: float | None = None
    reason: str = ""
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


class AgentConfirmationService:
    def __init__(self, timeout: float = TIMEOUT) -> None:
        self._timeout = timeout
        self._items: dict[str, Confirmation] = {}

    def _prune(self, now: float) -> None:
        for item in list(self._items.values()):
            if item.decision is Decision.PENDING and item.expires <= now:
                self._decide(item, Decision.EXPIRED, "no answer in time")
            if item.decided is not None and now - item.decided > KEEP_DECIDED:
                del self._items[item.id]

    def _decide(self, item: Confirmation, decision: Decision, reason: str = "") -> None:
        item.decision, item.decided, item.reason = decision, time.time(), reason
        item._event.set()
        logger.info("Assistant action %s %s: %s %s", item.id, decision.value, item.method, item.path)

    def list(self) -> list[Confirmation]:
        self._prune(time.time())
        return sorted(self._items.values(), key=lambda c: c.created)

    async def request(
        self, *, tool: str, summary: str, method: str, path: str, arguments: dict[str, Any], permission: str
    ) -> Confirmation:
        """Queue an action and wait for the operator (or the timeout)."""
        now = time.time()
        item = Confirmation(
            id=secrets.token_hex(6),
            tool=tool,
            summary=summary,
            method=method,
            path=path,
            arguments=arguments,
            permission=permission,
            created=now,
            expires=now + self._timeout,
        )
        self._items[item.id] = item
        logger.info("Assistant asks: %s %s (%s)", method, path, item.id)
        try:
            await asyncio.wait_for(item._event.wait(), timeout=self._timeout)
        except asyncio.TimeoutError:
            self._decide(item, Decision.EXPIRED, "no answer in time")
        except asyncio.CancelledError:
            # The agent gave up (client disconnected): nothing to approve.
            if item.decision is Decision.PENDING:
                self._decide(item, Decision.EXPIRED, "the assistant stopped waiting")
            raise
        return item

    def answer(self, confirmation_id: str, approve: bool, reason: str = "") -> Confirmation:
        """Approve or deny. ``KeyError``: unknown; ``ValueError``: already decided."""
        self._prune(time.time())
        item = self._items[confirmation_id]
        if item.decision is not Decision.PENDING:
            raise ValueError(f"already {item.decision.value}")
        self._decide(item, Decision.APPROVED if approve else Decision.DENIED, reason)
        return item


_service = AgentConfirmationService()


def get_agent_confirmation_service() -> AgentConfirmationService:
    return _service


__all__ = ["AgentConfirmationService", "Confirmation", "Decision", "get_agent_confirmation_service"]
