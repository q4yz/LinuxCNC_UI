// The assistant chat: transport seam, context, history storage, panel.
//
// Run with: ``node --test frontend/tests/test-agent-chat.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../src");
const chat = await import(pathToFileURL(resolve(src, "agent/agentChat.ts")).href);

function memoryStore() {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  };
}

test("without an agent the offline transport answers", async () => {
  chat.setAgentTransport(null);
  const transport = chat.agentTransport();
  assert.equal(transport.connected, false);
  assert.equal((await transport.send([chat.newMessage("user", "hi")])).text, chat.OFFLINE_REPLY);
});

test("an installed transport receives the conversation", async () => {
  const seen: unknown[] = [];
  chat.setAgentTransport({
    name: "test",
    connected: true,
    async send(history: unknown[], onPartial?: (t: string) => void) {
      seen.push(history);
      onPartial?.("par");
      return { text: "done" };
    },
  });
  const partials: string[] = [];
  const reply = await chat.agentTransport().send([chat.newMessage("user", "x")], (t: string) => partials.push(t));
  assert.equal(reply.text, "done");
  assert.deepEqual(partials, ["par"]);
  assert.equal(seen.length, 1);
  chat.setAgentTransport(null);
});

test("failed replies are not sent back as context", () => {
  const messages = [
    chat.newMessage("user", "a"),
    chat.newMessage("assistant", "boom", { error: true }),
    chat.newMessage("system", "note"),
    chat.newMessage("user", "b"),
  ];
  assert.deepEqual(chat.contextFor(messages).map((m: { text: string }) => m.text), ["a", "b"]);
});

test("message ids are unique", () => {
  const ids = new Set(Array.from({ length: 50 }, () => chat.newMessage("user", "x").id));
  assert.equal(ids.size, 50);
});

test("history round-trips, is capped, and drops junk", () => {
  const store = memoryStore();
  const many = Array.from({ length: chat.MAX_HISTORY + 10 }, (_, i) => chat.newMessage("user", String(i)));
  chat.saveHistory(many, store);
  const loaded = chat.loadHistory(store);
  assert.equal(loaded.length, chat.MAX_HISTORY);
  assert.equal(loaded.at(-1).text, String(chat.MAX_HISTORY + 9));
  store.setItem(chat.HISTORY_KEY, JSON.stringify([{ nope: 1 }, many[0]]));
  assert.equal(chat.loadHistory(store).length, 1);
  store.setItem(chat.HISTORY_KEY, "{not json");
  assert.deepEqual(chat.loadHistory(store), []);
  chat.saveHistory([], store);
  assert.equal(store.data.has(chat.HISTORY_KEY), false);
});

test("storage failures never break the chat", () => {
  const broken = {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("full"); },
    removeItem() { throw new Error("blocked"); },
  };
  assert.deepEqual(chat.loadHistory(broken), []);
  assert.doesNotThrow(() => chat.saveHistory([chat.newMessage("user", "x")], broken));
});

test("the panel is mounted in the shell, below the E-stop", () => {
  const app = readFileSync(resolve(src, "App.vue"), "utf-8");
  assert.match(app, /<AgentPanel \/>/);
  const panel = readFileSync(resolve(src, "components/agent/AgentPanel.vue"), "utf-8");
  assert.match(panel, /estopBox\(\)/, "the panel starts below the E-stop box");
  assert.match(panel, /data-testid="agent-tab"/);
  assert.match(panel, /event\.key === "Enter" && !event\.shiftKey/);
});

// -- the assistant's actions waiting for approval ------------------------- //

test("confirmations map to the entity (ms times, unknown decision = expired)", async () => {
  const src2 = resolve(here, "../src");
  const source = readFileSync(resolve(src2, "facades/agentConfirmationsFacade.ts"), "utf-8");
  assert.match(source, /AssistantService\.listAgentConfirmations/, "uses the generated client");
  assert.match(source, /created: Math\.round\(wire\.created \* 1000\)/);
  assert.match(source, /DECISIONS\.includes\(wire\.decision/);
});

test("the panel shows approval cards, a pending badge, and unfolds for a new request", () => {
  const panel = readFileSync(resolve(src, "components/agent/AgentPanel.vue"), "utf-8");
  assert.match(panel, /<AgentConfirmationCard/);
  assert.match(panel, /data-testid="agent-pending-badge"/);
  assert.match(panel, /agent\.startPolling\(\)/);
  const store = readFileSync(resolve(src, "stores/agentStore.ts"), "utf-8");
  assert.match(store, /if \(fresh\.length > 0\) open\.value = true/, "a new request unfolds the panel");
  assert.match(store, /console\.info\(`Assistant: \$\{approve \? "approved" : "denied"\}/, "decisions are logged");
  const card = readFileSync(resolve(src, "components/agent/AgentConfirmationCard.vue"), "utf-8");
  assert.match(card, /confirmation\.method[^\n]{0,40}confirmation\.path/, "the exact request is shown");
  assert.match(card, /data-testid="agent-approve"/);
  assert.match(card, /data-testid="agent-deny"/);
});

test("Settings → Assistant: connection panel and the actions switch", () => {
  const defs = readFileSync(resolve(src, "settings/definitions/assistant.ts"), "utf-8");
  assert.match(defs, /"assistant\.allow_actions",\s*true/, "on by default (each action still needs approval)");
  assert.match(readFileSync(resolve(src, "settings/definitions/index.ts"), "utf-8"), /import "\.\/assistant";/);
  const panel = readFileSync(resolve(src, "settings/components/SettingAssistantConnection.vue"), "utf-8");
  assert.match(panel, /agentConfirmationsFacade\.status\(\)/, "status from the MCP server's own catalog");
  assert.match(panel, /claude mcp add --transport http linuxcnc \$\{url\.value\}/);
  assert.match(panel, /"mcp-remote"/);
  assert.match(panel, /document\.execCommand\("copy"\)/, "copy works on plain http too");
  // the backend reads the same key
  const backend = readFileSync(resolve(here, "../../backend/system/services/AgentMcpService.py"), "utf-8");
  assert.match(backend, /ALLOW_ACTIONS_KEY = "assistant\.allow_actions"/);
});
