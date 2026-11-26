"""The in-app assistant: Claude, with the MCP server's tools, in the panel.

A conversation lives here (in memory; a restart forgets it). Each
operator message starts a run: a Messages API tool loop, streamed, whose
tools are exactly the MCP catalog's (:class:`services.AgentMcpService.ToolCatalog`)
— same agent role, same permission check, and the same operator
approval for actions (a tool call that needs it waits for the card in
the panel). The UI polls the conversation for the reply as it streams.

The API history is append-only (Claude Opus 5.5 checks replayed
thinking against it); the only edit is the documented one after a
mid-output refusal fallback (:func:`echo_content`).

Every user turn sent to the model — the operator's message and each
round of tool results — carries a fresh ``<machine_state>`` block
(:mod:`services.MachineSummaryService`), stored with that turn: the
operator acts on the machine between messages, and the assistant must
not answer from an E-stop it saw earlier.
"""
from __future__ import annotations

import asyncio
import functools
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import anthropic

from services.AssistantConfigService import AssistantConfig, get_assistant_config_service

logger = logging.getLogger("backend.system.assistant")

#: Most tool rounds for one operator message.
MAX_ROUNDS = 25
#: Output cap per model turn (streamed, so no timeout concern).
MAX_TOKENS = 64000
#: Conversations kept in memory (the oldest idle ones go first).
MAX_CONVERSATIONS = 20
#: Consecutive re-tries of a turn whose tool input the SDK could not parse.
MAX_JSON_RETRIES = 2
FALLBACK_BETA = "server-side-fallback-2026-07-01"
#: Models with server-side refusal fallbacks (Haiku has none).
FALLBACK_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-2")

SYSTEM_PROMPT = """\
You are the assistant built into LinuxCNC UI, the web interface of a LinuxCNC machine \
(a CNC mill, router or 3D printer). The operator chats with you in a side panel next to the \
machine's controls, usually standing at the machine.

Use the tools to look things up instead of guessing. machine_* tools reach the running machine \
(state, positions, temperatures, I/O, calibrations, the loaded program); system_* tools reach the \
always-on system service (program files, machine profiles, macros, settings, versions). Machine \
tools are missing while LinuxCNC is stopped; say so when that is why you cannot answer.

Actions that move, heat or change the machine appear to the operator as a card and run only if \
they approve. Before calling such a tool, say in one sentence what you will do and why. A denial \
comes back as an error with their reason: accept it, and do not retry the action unless they ask. \
Never try to work around a denial or a permission error.

Every operator message and every round of tool results comes with a <machine_state> block taken \
just then (state, E-stop, homing, program, temperatures). It is the current truth: it supersedes \
earlier tool results and earlier snapshots, so never assume an older state (e.g. an E-stop that \
has since been reset). Do not repeat it back unless it matters for the answer.

The machine is physical. Before suggesting motion, think about homing, the E-stop, temperatures, \
clamps and tool clearance; when unsure, explain rather than act. If something looks dangerous, \
engage the E-stop.

Answer briefly and practically, in plain text (the panel shows no Markdown): short paragraphs or \
simple "- " lists, numbers with units."""


@dataclass
class ChatEntry:
    id: str
    role: str  # user | assistant | tool | error
    text: str
    time: float
    tool: str | None = None
    #: tool entries: running | done | error
    status: str = ""


@dataclass
class Conversation:
    id: str
    history: list[dict[str, Any]] = field(default_factory=list)
    #: The operator's message waiting to go into the history (with its snapshot).
    pending: str = ""
    entries: list[ChatEntry] = field(default_factory=list)
    busy: bool = False
    partial: str = ""
    model: str = ""
    updated: float = field(default_factory=time.time)
    task: asyncio.Task[None] | None = None

    def add(self, role: str, text: str, **extra: Any) -> ChatEntry:
        entry = ChatEntry(id=secrets.token_hex(4), role=role, text=text, time=time.time(), **extra)
        self.entries.append(entry)
        self.updated = entry.time
        return entry


class AssistantNotConfigured(RuntimeError):
    pass


class ConversationBusy(RuntimeError):
    pass


def echo_content(content: list[Any]) -> list[Any]:
    """The assistant turn as it goes back into the history. After a
    mid-output refusal fallback, blocks of the declined attempt (thinking,
    tool calls) before the last ``fallback`` block are left out — the
    ``fallback`` block itself stays where it is."""
    last = max((i for i, b in enumerate(content) if getattr(b, "type", None) == "fallback"), default=-1)
    if last < 0:
        return list(content)
    drop = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}
    return [b for i, b in enumerate(content) if i >= last or getattr(b, "type", None) not in drop]


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """``schema`` with its ``$defs`` references inlined (cycles become ``{}``)."""
    defs = schema.get("$defs") or {}

    def walk(node: Any, seen: tuple[str, ...]) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.rsplit("/", 1)[1]
                if name in seen or name not in defs:
                    return {}
                merged = {**walk(defs[name], seen + (name,)), **{k: walk(v, seen) for k, v in node.items() if k != "$ref"}}
                return merged
            return {k: walk(v, seen) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v, seen) for v in node]
        return node

    return walk(schema, ())


class AssistantChatService:
    def __init__(
        self,
        catalog: Callable[[], Any] | None = None,
        client_factory: Callable[[AssistantConfig], Any] | None = None,
        summary: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        self._catalog = catalog or _mcp_catalog
        self._summary = summary or _machine_summary
        self._client_factory: Callable[[AssistantConfig], Any] = client_factory or _anthropic_client
        self._conversations: dict[str, Conversation] = {}

    # -- conversations ------------------------------------------------------ #

    def get(self, conversation_id: str) -> Conversation:
        return self._conversations[conversation_id]

    def delete(self, conversation_id: str) -> None:
        conv = self._conversations.pop(conversation_id, None)
        if conv and conv.task and not conv.task.done():
            conv.task.cancel()

    def stop(self, conversation_id: str) -> Conversation:
        conv = self._conversations[conversation_id]
        if conv.task and not conv.task.done():
            conv.task.cancel()
        return conv

    def _new(self) -> Conversation:
        idle = sorted((c for c in self._conversations.values() if not c.busy), key=lambda c: c.updated)
        while len(self._conversations) >= MAX_CONVERSATIONS and idle:
            self._conversations.pop(idle.pop(0).id, None)
        conv = Conversation(id=secrets.token_hex(8))
        self._conversations[conv.id] = conv
        return conv

    def send(self, conversation_id: str | None, text: str) -> Conversation:
        """Add the operator's message and start the reply (in the background).
        ``KeyError``: unknown conversation; ``ConversationBusy``; ``AssistantNotConfigured``."""
        config = get_assistant_config_service().get()
        if not config.configured:
            raise AssistantNotConfigured("No Anthropic API key is set (Settings → Assistant).")
        conv = self._conversations[conversation_id] if conversation_id else self._new()
        if conv.busy:
            raise ConversationBusy("The assistant is still answering.")
        # into the history at the start of the run, with a machine snapshot
        conv.pending = text
        conv.add("user", text)
        conv.busy, conv.partial, conv.model = True, "", config.model
        task = asyncio.get_running_loop().create_task(self._run(conv, config))
        task.add_done_callback(functools.partial(self._settle_task, conv))
        conv.task = task
        return conv

    @staticmethod
    def _settle_task(conv: Conversation, _task: "asyncio.Task[None]") -> None:
        AssistantChatService._settle(conv)

    @staticmethod
    def _settle(conv: Conversation) -> None:
        """A run cancelled before it started never reaches its own cleanup."""
        if conv.busy:
            AssistantChatService._close_open_tool_calls(conv, "Stopped by the operator.")
            conv.add("error", "Stopped.")
            conv.busy, conv.partial, conv.task = False, "", None

    # -- the tool loop ---------------------------------------------------- #

    async def _run(self, conv: Conversation, config: AssistantConfig) -> None:
        try:
            await self._loop(conv, config)
        except asyncio.CancelledError:
            self._close_open_tool_calls(conv, "Stopped by the operator.")
            conv.add("error", "Stopped.")
        except Exception as exc:  # noqa: BLE001 - shown in the panel, not raised
            logger.exception("Assistant run failed")
            self._close_open_tool_calls(conv, "The run failed.")
            conv.add("error", f"The assistant failed: {exc}")
        finally:
            conv.busy, conv.partial, conv.task = False, "", None

    async def _state_block(self) -> dict[str, Any]:
        """The ``<machine_state>`` text block for the next user turn."""
        try:
            text = await self._summary()
        except Exception as exc:  # noqa: BLE001 - the reply must not fail on it
            logger.warning("machine summary failed: %s", exc)
            text = "<machine_state>unknown (could not be read)</machine_state>"
        return {"type": "text", "text": text}

    async def _loop(self, conv: Conversation, config: AssistantConfig) -> None:
        text, conv.pending = conv.pending, ""
        conv.history.append({"role": "user", "content": [await self._state_block(), {"type": "text", "text": text}]})
        catalog = self._catalog()
        if catalog is None:
            conv.add("error", "The MCP server is not running, so the assistant has no tools.")
            return
        tools = await catalog.tools()
        api_tools = [
            {
                "name": t.name,
                "description": t.description[:4000],
                "input_schema": inline_refs(t.input_schema),
                "eager_input_streaming": True,
            }
            for t in tools.values()
        ]
        client = self._client_factory(config)
        json_retries = 0
        for _ in range(MAX_ROUNDS):
            params: dict[str, Any] = {
                "model": config.model,
                "max_tokens": MAX_TOKENS,
                "system": SYSTEM_PROMPT,
                "tools": api_tools,
                "messages": conv.history,
                "output_config": {"effort": config.effort},
                "cache_control": {"type": "ephemeral"},
            }
            if config.model in FALLBACK_MODELS:
                params["betas"] = [FALLBACK_BETA]
                params["fallbacks"] = "default"
            conv.partial = ""
            try:
                async with client.beta.messages.stream(**params) as stream:
                    async for event in stream:
                        if event.type == "text":
                            conv.partial += str(getattr(event, "text", ""))
                    message = await stream.get_final_message()
                json_retries = 0
            except ValueError:
                # Tool input the SDK could not parse at all: no tool_use id to
                # answer, so re-run the turn (bounded). API errors aren't ValueError.
                json_retries += 1
                if json_retries > MAX_JSON_RETRIES:
                    conv.add("error", "The assistant produced a tool call that could not be read.")
                    return
                continue
            except anthropic.AuthenticationError:
                conv.add("error", "The Anthropic API key was rejected (Settings → Assistant).")
                return
            except anthropic.PermissionDeniedError as exc:
                conv.add("error", f"The API key may not use {config.model}: {exc.message}")
                return
            except anthropic.RateLimitError:
                conv.add("error", "Rate limited by the Anthropic API. Try again in a minute.")
                return
            except anthropic.APIStatusError as exc:
                conv.add("error", f"Anthropic API error {exc.status_code}: {exc.message}")
                return
            except anthropic.APIConnectionError:
                conv.add("error", "Could not reach the Anthropic API (internet connection?).")
                return

            content = echo_content(list(message.content))
            conv.history.append({"role": "assistant", "content": content})
            text = "".join(getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text").strip()
            conv.partial = ""
            if text:
                conv.add("assistant", text)

            if message.stop_reason == "pause_turn":
                continue
            tool_uses = [b for b in content if getattr(b, "type", None) == "tool_use"]
            if message.stop_reason == "refusal":
                self._close_open_tool_calls(conv, "Not run: the request was declined.")
                conv.add("error", "The model declined this request.")
                return
            if not tool_uses:
                return
            if message.stop_reason == "max_tokens":
                self._close_open_tool_calls(conv, "Not run: the tool call was cut off.")
                conv.add("error", "The reply was cut off before the tool call was complete.")
                return

            results = []
            for block in tool_uses:
                tool = tools.get(block.name)
                entry = conv.add("tool", tool.summary if tool else block.name, tool=block.name, status="running")
                if not isinstance(block.input, dict):
                    entry.status = "error"
                    results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                    "content": json.dumps({"INVALID_JSON": json.dumps(block.input)})})
                    continue
                result = await catalog.call(block.name, block.input)
                entry.status = "error" if result.is_error else "done"
                text_out = "\n".join(getattr(c, "text", "") for c in result.content) or "(no output)"
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": text_out,
                                "is_error": bool(result.is_error)})
            # the tools may have changed the machine: a fresh look with the results
            conv.history.append({"role": "user", "content": [*results, await self._state_block()]})
        conv.add("error", f"Stopped after {MAX_ROUNDS} tool rounds.")

    @staticmethod
    def _close_open_tool_calls(conv: Conversation, why: str) -> None:
        """Answer tool calls of the last assistant turn that have no result
        yet, so the history stays valid for the next message."""
        if not conv.history or conv.history[-1].get("role") != "assistant":
            return
        content = conv.history[-1].get("content")
        ids = [b.id for b in content if getattr(b, "type", None) == "tool_use"] if isinstance(content, list) else []
        if ids:
            conv.history.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": i, "content": why, "is_error": True} for i in ids
            ]})
        for entry in conv.entries:
            if entry.role == "tool" and entry.status == "running":
                entry.status = "error"


def _anthropic_client(config: AssistantConfig) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=config.api_key)


async def _machine_summary() -> str:
    from services.MachineSummaryService import machine_summary

    return await machine_summary()


def _mcp_catalog() -> Any:
    from services.AgentMcpService import mcp_endpoint

    return mcp_endpoint.catalog


_service = AssistantChatService()


def get_assistant_chat_service() -> AssistantChatService:
    return _service


__all__ = [
    "AssistantChatService", "AssistantNotConfigured", "ChatEntry", "Conversation", "ConversationBusy",
    "SYSTEM_PROMPT", "echo_content", "get_assistant_chat_service", "inline_refs",
]
