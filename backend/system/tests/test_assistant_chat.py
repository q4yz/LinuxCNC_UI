"""The in-app assistant: the tool loop (against a scripted fake of the
Claude API), its settings store, and its routes."""
from __future__ import annotations

import asyncio
import os
import stat
from types import SimpleNamespace as NS
from typing import Any

import anthropic
import httpx2
import pytest
from mcp import types

from core.openapi_tools import AgentTool
from services import AssistantChatService as chat_module
from services.AssistantChatService import (
    MAX_TOKENS,
    SYSTEM_PROMPT,
    AssistantChatService,
    AssistantNotConfigured,
    echo_content,
    inline_refs,
)
from services.AssistantConfigService import AssistantConfig, AssistantConfigService

# -- fakes ------------------------------------------------------------------- #


def text(t):
    return NS(type="text", text=t)


def tool_use(name, args, id_="tu1"):
    return NS(type="tool_use", id=id_, name=name, input=args)


def message(*blocks, stop="end_turn"):
    return NS(content=list(blocks), stop_reason=stop)


class FakeStream:
    def __init__(self, msg):
        self._msg = msg

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for block in self._msg.content:
                if block.type == "text":
                    for word in block.text.split(" "):
                        yield NS(type="text", text=word + " ")
        return gen()

    async def get_final_message(self):
        return self._msg


class FakeClient:
    """Answers each turn with the next scripted message (or raises it)."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **params):
        self.calls.append({**params, "messages": list(params["messages"])})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return FakeStream(step)


def tool(name, summary, level="allow", schema=None):
    return AgentTool(backend="machine", name=name, method="GET" if level == "allow" else "POST", path="/x",
                     summary=summary, description=summary, input_schema=schema or {"type": "object", "properties": {}},
                     permission="machine.read", level=level)


class FakeCatalog:
    def __init__(self, results=None, wait: asyncio.Event | None = None):
        self._tools = {
            "machine_get_state": tool("machine_get_state", "Read Machine State", schema={
                "type": "object", "properties": {"body": {"$ref": "#/$defs/Req"}},
                "$defs": {"Req": {"type": "object", "properties": {"x": {"type": "number"}}}}}),
            "machine_post_mdi": tool("machine_post_mdi", "Run MDI Command", level="confirm"),
        }
        self.results = results or {}
        self.called: list[tuple[str, Any]] = []
        self.wait = wait

    async def tools(self):
        return self._tools

    async def call(self, name, args):
        self.called.append((name, args))
        if self.wait is not None:
            await self.wait.wait()
        ok, out = self.results.get(name, (True, '{"state": "on"}'))
        return types.CallToolResult(content=[types.TextContent(type="text", text=out)], is_error=not ok)


CONFIG = AssistantConfig(api_key="sk-test-1234567890", model="claude-opus-5-5", effort="medium", key_source="stored")


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(chat_module, "get_assistant_config_service", lambda: NS(get=lambda: CONFIG))


def service(script, catalog=None):
    client = FakeClient(script)
    svc = AssistantChatService(catalog=lambda: catalog or FakeCatalog(), client_factory=lambda cfg: client)
    return svc, client


async def finish(svc, conv):
    for _ in range(500):
        if not conv.busy:
            return conv
        await asyncio.sleep(0.005)
    raise AssertionError("still busy")


def roles(conv):
    return [(e.role, e.text) for e in conv.entries]


# -- the loop ---------------------------------------------------------------- #


def test_a_plain_answer_and_the_request_it_sends():
    async def go():
        svc, client = service([message(text("Hello, the machine is idle."))])
        conv = await finish(svc, svc.send(None, "hi"))
        assert roles(conv) == [("user", "hi"), ("assistant", "Hello, the machine is idle.")]
        params = client.calls[0]
        assert params["model"] == "claude-opus-5-5" and params["max_tokens"] == MAX_TOKENS
        assert params["system"] == SYSTEM_PROMPT and params["output_config"] == {"effort": "medium"}
        assert params["fallbacks"] == "default" and params["betas"] == ["server-side-fallback-2026-07-01"]
        assert params["cache_control"] == {"type": "ephemeral"}
        assert "thinking" not in params and "temperature" not in params
        names = [t["name"] for t in params["tools"]]
        assert names == ["machine_get_state", "machine_post_mdi"]
        state = params["tools"][0]
        assert state["eager_input_streaming"] is True
        assert "$defs" not in state["input_schema"]  # refs inlined
        assert state["input_schema"]["properties"]["body"]["properties"]["x"] == {"type": "number"}

    asyncio.run(go())


def test_tools_run_through_the_catalog_and_results_go_back():
    async def go():
        catalog = FakeCatalog()
        svc, client = service([
            message(text("Let me check."), tool_use("machine_get_state", {}), stop="tool_use"),
            message(text("It is on.")),
        ], catalog)
        conv = await finish(svc, svc.send(None, "state?"))
        assert catalog.called == [("machine_get_state", {})]
        assert roles(conv) == [("user", "state?"), ("assistant", "Let me check."), ("tool", "Read Machine State"),
                               ("assistant", "It is on.")]
        assert conv.entries[2].status == "done"
        second = client.calls[1]["messages"]
        assert second[-1] == {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu1", "content": '{"state": "on"}', "is_error": False}]}
        # history is append-only: the first turn's messages are a prefix of the second's
        assert client.calls[1]["messages"][: len(client.calls[0]["messages"])] == client.calls[0]["messages"]

    asyncio.run(go())


def test_a_denied_action_comes_back_as_an_error_result():
    async def go():
        catalog = FakeCatalog(results={"machine_post_mdi": (False, "The operator declined: busy. Nothing was done.")})
        svc, client = service([
            message(tool_use("machine_post_mdi", {"body": {"command": "G28"}}), stop="tool_use"),
            message(text("Okay, I will not home.")),
        ], catalog)
        conv = await finish(svc, svc.send(None, "home it"))
        assert conv.entries[1].status == "error"
        result = client.calls[1]["messages"][-1]["content"][0]
        assert result["is_error"] is True and "declined" in result["content"]

    asyncio.run(go())


def test_refusal_and_truncation_close_open_tool_calls():
    for stop, why in (("refusal", "declined"), ("max_tokens", "cut off")):
        async def go():
            svc, client = service([message(tool_use("machine_post_mdi", {}), stop=stop)])
            conv = await finish(svc, svc.send(None, "x"))
            assert conv.entries[-1].role == "error" and why in conv.entries[-1].text
            last = conv.history[-1]
            assert last["role"] == "user" and last["content"][0]["tool_use_id"] == "tu1"  # history stays valid

        asyncio.run(go())


def test_api_errors_are_shown_not_raised():
    def auth_error():
        response = httpx2.Response(401, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
        return anthropic.AuthenticationError("invalid x-api-key", response=response, body=None)

    async def go():
        svc, _ = service([auth_error()])
        conv = await finish(svc, svc.send(None, "x"))
        assert conv.entries[-1].role == "error" and "rejected" in conv.entries[-1].text
        assert not conv.busy

    asyncio.run(go())


def test_an_unparseable_tool_call_is_retried_then_given_up():
    async def go():
        svc, client = service([ValueError("bad json"), message(text("Done."))])
        conv = await finish(svc, svc.send(None, "x"))
        assert roles(conv)[-1] == ("assistant", "Done.") and len(client.calls) == 2

    asyncio.run(go())


def test_stopping_while_an_action_waits_for_approval():
    async def go():
        catalog = FakeCatalog(wait=asyncio.Event())  # never approved
        svc, _ = service([message(tool_use("machine_post_mdi", {}), stop="tool_use")], catalog)
        conv = svc.send(None, "home")
        for _ in range(200):
            if catalog.called:
                break
            await asyncio.sleep(0.005)
        svc.stop(conv.id)
        await finish(svc, conv)
        assert conv.entries[-1].text == "Stopped." and conv.entries[1].status == "error"
        assert conv.history[-1]["content"][0]["content"] == "Stopped by the operator."

    asyncio.run(go())


def test_one_reply_at_a_time_and_a_key_is_needed(monkeypatch):
    async def go():
        svc, _ = service([message(text("a")), message(text("b"))], FakeCatalog(wait=asyncio.Event()))
        conv = svc.send(None, "x")
        with pytest.raises(chat_module.ConversationBusy):
            svc.send(conv.id, "y")
        svc.stop(conv.id)
        await finish(svc, conv)

    asyncio.run(go())
    monkeypatch.setattr(chat_module, "get_assistant_config_service",
                        lambda: NS(get=lambda: AssistantConfig("", "claude-opus-5-5", "medium", "")))
    with pytest.raises(AssistantNotConfigured):
        AssistantChatService(catalog=lambda: None).send(None, "x")


def test_haiku_has_no_server_side_fallback(monkeypatch):
    haiku = AssistantConfig("sk-test-1234567890", "claude-haiku-5-5", "low", "stored")
    monkeypatch.setattr(chat_module, "get_assistant_config_service", lambda: NS(get=lambda: haiku))

    async def go():
        svc, client = service([message(text("ok"))])
        await finish(svc, svc.send(None, "x"))
        assert "fallbacks" not in client.calls[0] and "betas" not in client.calls[0]

    asyncio.run(go())


def test_echo_after_a_mid_output_fallback():
    blocks = [NS(type="thinking"), text("partial"), NS(type="tool_use"), NS(type="fallback"), NS(type="thinking"), text("ok")]
    assert [b.type for b in echo_content(blocks)] == ["text", "fallback", "thinking", "text"]
    plain = [NS(type="thinking"), text("a")]
    assert echo_content(plain) == plain


def test_inline_refs_handles_cycles():
    schema = {"type": "object", "properties": {"n": {"$ref": "#/$defs/Node"}},
              "$defs": {"Node": {"type": "object", "properties": {"next": {"$ref": "#/$defs/Node"}}}}}
    out = inline_refs(schema)
    assert out["properties"]["n"]["properties"]["next"] == {} and "$defs" not in out


# -- settings ---------------------------------------------------------------- #


def test_the_key_is_stored_private_and_never_shown(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    store = AssistantConfigService(tmp_path / "data" / "assistant.json")
    assert not store.get().configured
    cfg = store.update(api_key="  sk-ant-abcdefgh1234  ", model="claude-sonnet-5-5")
    assert cfg.configured and cfg.key_hint == "…1234" and cfg.model == "claude-sonnet-5-5" and cfg.key_source == "stored"
    assert stat.S_IMODE(os.stat(tmp_path / "data" / "assistant.json").st_mode) == 0o600
    with pytest.raises(ValueError):
        store.update(model="gpt-4")
    assert store.update(api_key="").configured is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-key-9999")
    assert store.get().key_source == "environment"


def test_the_routes_never_return_the_key(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import agent_chat
    from services import AssistantConfigService as cfg_module

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(agent_chat, "get_assistant_config_service", lambda: cfg_module.AssistantConfigService(tmp_path / "a.json"))
    app = FastAPI()
    app.include_router(agent_chat.router)
    client = TestClient(app)
    put = client.put("/api/v1/agent/config", json={"api_key": "sk-ant-secret-value-7777", "effort": "low"})
    assert put.status_code == 200 and "secret" not in put.text and put.json()["key_hint"] == "…7777"
    got = client.get("/api/v1/agent/config").json()
    assert got["configured"] and got["effort"] == "low" and [m["id"] for m in got["models"]][0] == "claude-opus-5-5"
    assert client.put("/api/v1/agent/config", json={"model": "nope"}).status_code == 400
    assert client.get("/api/v1/agent/chat/unknown").status_code == 404
