"""``/api/v1/agent/chat`` and ``/api/v1/agent/config`` — the in-app
assistant (``services/AssistantChatService.py``). The API key is
write-only: reads report only whether one is set and its last four
characters."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from services.AssistantChatService import (
    AssistantNotConfigured,
    Conversation,
    ConversationBusy,
    get_assistant_chat_service,
)
from services.AssistantConfigService import EFFORTS, MODELS, AssistantConfig, get_assistant_config_service

router = APIRouter(prefix="/api/v1/agent", tags=["assistant"])

_ID = Path(..., description="The conversation's id.")


class AssistantModelOption(BaseModel):
    id: str
    label: str


class AssistantConfigResponse(BaseModel):
    configured: bool = Field(..., description="An API key is available.")
    key_source: str = Field("", description="stored, environment, or empty.")
    key_hint: str = Field("", description="The key's last four characters.")
    model: str
    effort: str
    models: list[AssistantModelOption]
    efforts: list[str]


class AssistantConfigRequest(BaseModel):
    api_key: Optional[str] = Field(None, description="New Anthropic API key; an empty string removes the stored one.")
    model: Optional[str] = None
    effort: Optional[str] = None


class ChatEntryResponse(BaseModel):
    id: str
    role: str = Field(..., description="user, assistant, tool or error.")
    text: str
    time: float
    tool: Optional[str] = None
    status: str = Field("", description="Tool entries: running, done or error.")


class ConversationResponse(BaseModel):
    id: str
    busy: bool = Field(..., description="A reply is being written.")
    partial: str = Field("", description="The reply streaming in right now.")
    model: str = ""
    entries: list[ChatEntryResponse]


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=20000)
    conversation_id: Optional[str] = Field(None, description="Continue this conversation; empty: a new one.")


def _config(cfg: AssistantConfig) -> AssistantConfigResponse:
    return AssistantConfigResponse(
        configured=cfg.configured,
        key_source=cfg.key_source,
        key_hint=cfg.key_hint,
        model=cfg.model,
        effort=cfg.effort,
        models=[AssistantModelOption(id=i, label=label) for i, label in MODELS],
        efforts=list(EFFORTS),
    )


def _conversation(conv: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=conv.id,
        busy=conv.busy,
        partial=conv.partial,
        model=conv.model,
        entries=[ChatEntryResponse(id=e.id, role=e.role, text=e.text, time=e.time, tool=e.tool, status=e.status)
                 for e in conv.entries],
    )


@router.get("/config", response_model=AssistantConfigResponse, summary="The in-app assistant's settings",
            description="Whether an Anthropic API key is set (never the key), the model and the effort.",
            operation_id="getAssistantConfig")
def get_config() -> AssistantConfigResponse:
    return _config(get_assistant_config_service().get())


@router.put("/config", response_model=AssistantConfigResponse, summary="Change the in-app assistant's settings",
            operation_id="updateAssistantConfig", responses={400: {"description": "Unknown model or effort."}})
def update_config(body: AssistantConfigRequest) -> AssistantConfigResponse:
    try:
        return _config(get_assistant_config_service().update(api_key=body.api_key, model=body.model, effort=body.effort))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/chat", response_model=ConversationResponse, summary="Send a message to the in-app assistant",
             description="Starts the reply in the background; poll the conversation for it.",
             operation_id="sendAssistantMessage",
             responses={404: {"description": "Unknown conversation."}, 409: {"description": "Still answering."},
                        412: {"description": "No API key set."}})
async def send(body: ChatRequest) -> ConversationResponse:
    try:
        return _conversation(get_assistant_chat_service().send(body.conversation_id, body.message))
    except KeyError:
        raise HTTPException(404, "Unknown conversation (the system service may have restarted).") from None
    except ConversationBusy as exc:
        raise HTTPException(409, str(exc)) from None
    except AssistantNotConfigured as exc:
        raise HTTPException(412, str(exc)) from None


@router.get("/chat/{conversation_id}", response_model=ConversationResponse, summary="A conversation with the assistant",
            operation_id="getAssistantConversation", responses={404: {"description": "Unknown conversation."}})
def get_conversation(conversation_id: str = _ID) -> ConversationResponse:
    try:
        return _conversation(get_assistant_chat_service().get(conversation_id))
    except KeyError:
        raise HTTPException(404, "Unknown conversation.") from None


@router.post("/chat/{conversation_id}/stop", response_model=ConversationResponse, summary="Stop the assistant's reply",
             operation_id="stopAssistantReply", responses={404: {"description": "Unknown conversation."}})
def stop(conversation_id: str = _ID) -> ConversationResponse:
    try:
        return _conversation(get_assistant_chat_service().stop(conversation_id))
    except KeyError:
        raise HTTPException(404, "Unknown conversation.") from None


@router.delete("/chat/{conversation_id}", status_code=204, summary="Forget a conversation",
               operation_id="deleteAssistantConversation")
def delete(conversation_id: str = _ID) -> None:
    get_assistant_chat_service().delete(conversation_id)


__all__ = ["router"]
