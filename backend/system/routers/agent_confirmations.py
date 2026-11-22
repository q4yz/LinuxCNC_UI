"""``/api/v1/agent`` — the assistant: its MCP server's status, and its
actions waiting for the operator (``services/AgentConfirmationService.py``;
answering needs ``agent.approve``, which the agent role never has)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from services.AgentConfirmationService import Confirmation, get_agent_confirmation_service

router = APIRouter(prefix="/api/v1/agent", tags=["assistant"])

_ID = Path(..., description="The confirmation's id.")


class AgentConfirmationResponse(BaseModel):
    id: str
    tool: str = Field(..., description="The MCP tool the assistant called.")
    summary: str = Field(..., description="What the action does (the operation's summary).")
    method: str
    path: str = Field(..., description="The REST path the action will call.")
    arguments: dict[str, Any] = Field(default_factory=dict, description="The tool call's arguments.")
    permission: str
    decision: str = Field(..., description="pending, approved, denied or expired.")
    reason: str = ""
    created: float = Field(..., description="Unix time the assistant asked.")
    expires: float = Field(..., description="Unix time the request expires unanswered.")


class AgentConfirmationListResponse(BaseModel):
    confirmations: list[AgentConfirmationResponse]


class AgentDecisionRequest(BaseModel):
    reason: str = Field("", description="Optional note passed back to the assistant.")


def _response(item: Confirmation) -> AgentConfirmationResponse:
    return AgentConfirmationResponse(
        id=item.id,
        tool=item.tool,
        summary=item.summary,
        method=item.method,
        path=item.path,
        arguments=item.arguments,
        permission=item.permission,
        decision=item.decision.value,
        reason=item.reason,
        created=item.created,
        expires=item.expires,
    )


class AgentStatusResponse(BaseModel):
    mcp_path: str = Field(..., description="Where the MCP server listens (on this host).")
    running: bool = Field(..., description="The MCP server is up.")
    actions_allowed: bool = Field(..., description="The assistant may ask to run actions (assistant.allow_actions).")
    tools: dict[str, int] = Field(default_factory=dict, description="Tools offered now, per backend.")
    tools_needing_approval: int = Field(0, description="Of those, how many wait for the operator.")
    pending: int = Field(0, description="Actions waiting for approval now.")


@router.get(
    "/status",
    response_model=AgentStatusResponse,
    summary="The assistant's MCP server: address and what it offers",
    operation_id="getAgentStatus",
)
async def status() -> AgentStatusResponse:
    from services.AgentMcpService import actions_allowed, mcp_endpoint

    catalog = mcp_endpoint.catalog
    tools = list((await catalog.tools()).values()) if catalog else []
    per_backend: dict[str, int] = {}
    for tool in tools:
        per_backend[tool.backend] = per_backend.get(tool.backend, 0) + 1
    pending = sum(1 for c in get_agent_confirmation_service().list() if c.decision.value == "pending")
    return AgentStatusResponse(
        mcp_path="/mcp",
        running=catalog is not None,
        actions_allowed=actions_allowed(),
        tools=per_backend,
        tools_needing_approval=sum(1 for t in tools if t.level == "confirm"),
        pending=pending,
    )


@router.get(
    "/confirmations",
    response_model=AgentConfirmationListResponse,
    summary="The assistant's actions waiting for approval",
    description="Pending requests, plus those decided in the last 30 s.",
    operation_id="listAgentConfirmations",
)
def list_confirmations() -> AgentConfirmationListResponse:
    return AgentConfirmationListResponse(confirmations=[_response(c) for c in get_agent_confirmation_service().list()])


def _answer(confirmation_id: str, approve: bool, body: AgentDecisionRequest | None) -> AgentConfirmationResponse:
    try:
        item = get_agent_confirmation_service().answer(confirmation_id, approve, (body.reason if body else "").strip())
    except KeyError:
        raise HTTPException(404, "No such request (it may have expired).") from None
    except ValueError as exc:
        raise HTTPException(409, f"The request is {exc}.") from None
    return _response(item)


@router.post(
    "/confirmations/{confirmation_id}/approve",
    response_model=AgentConfirmationResponse,
    summary="Approve an action of the assistant",
    description="The assistant's request runs right away, as it was shown.",
    operation_id="approveAgentConfirmation",
    responses={404: {"description": "Unknown or expired."}, 409: {"description": "Already decided."}},
)
def approve(confirmation_id: str = _ID, body: AgentDecisionRequest | None = None) -> AgentConfirmationResponse:
    return _answer(confirmation_id, True, body)


@router.post(
    "/confirmations/{confirmation_id}/deny",
    response_model=AgentConfirmationResponse,
    summary="Deny an action of the assistant",
    description="The assistant is told the operator declined (with the reason, if any).",
    operation_id="denyAgentConfirmation",
    responses={404: {"description": "Unknown or expired."}, 409: {"description": "Already decided."}},
)
def deny(confirmation_id: str = _ID, body: AgentDecisionRequest | None = None) -> AgentConfirmationResponse:
    return _answer(confirmation_id, False, body)


__all__ = ["router"]
