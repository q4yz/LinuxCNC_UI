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

test("without an agent the offline transport answers (and says where to set it up)", async () => {
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
  assert.match(defs, /new PanelSetting\("Assistant", "In-app assistant \(Claude\)"/);
  const panel = readFileSync(resolve(src, "settings/components/SettingAssistantConnection.vue"), "utf-8");
  assert.match(panel, /agentConfirmationsFacade\.status\(\)/, "status from the MCP server's own catalog");
  assert.match(panel, /claude mcp add --transport http linuxcnc \$\{url\.value\}/);
  assert.match(panel, /"mcp-remote"/);
  assert.match(panel, /document\.execCommand\("copy"\)/, "copy works on plain http too");
  // the backend reads the same key
  const backend = readFileSync(resolve(here, "../../backend/system/services/AgentMcpService.py"), "utf-8");
  assert.match(backend, /ALLOW_ACTIONS_KEY = "assistant\.allow_actions"/);
});

// -- the in-app assistant (Claude via the system service) ------------------ //

const transportMod = await import(pathToFileURL(resolve(src, "agent/backendTransport.ts")).href);

function entry(role: string, text: string, status = "") {
  return { id: text, role, text, time: 0, tool: role === "tool" ? "t" : null, status };
}

test("a run renders tool lines, answers and the streaming part", () => {
  const conv = {
    id: "c", busy: true, partial: "streaming", model: "m",
    entries: [entry("user", "old"), entry("assistant", "old answer"), entry("user", "new"),
              entry("assistant", "Let me check."), entry("tool", "Read Machine State", "done"),
              entry("tool", "Run MDI Command", "running")],
  };
  const run = transportMod.runEntries(conv);
  assert.deepEqual(run.map((e: { text: string }) => e.text), ["Let me check.", "Read Machine State", "Run MDI Command"]);
  assert.equal(transportMod.renderRun(run, conv.partial),
    "Let me check.\n\n-> Read Machine State\n\n-> Run MDI Command ...\n\nstreaming");
});

test("the transport uses the generated client, keeps the conversation id, and stops on abort", () => {
  const source = readFileSync(resolve(src, "agent/backendTransport.ts"), "utf-8");
  assert.match(source, /assistantFacade\.send\(/);
  assert.match(source, /errorStatus\(err\) === 404 && conversationId/, "a forgotten conversation starts a new one");
  assert.match(source, /signal\?\.aborted && !stopping/);
  const facade = readFileSync(resolve(src, "facades/assistantFacade.ts"), "utf-8");
  assert.match(facade, /AssistantService\.sendAssistantMessage/);
  assert.doesNotMatch(facade, /api_key: [^n]*\bconfig\b/, "the key is only ever sent, never read back");
  const store = readFileSync(resolve(src, "stores/agentStore.ts"), "utf-8");
  assert.match(store, /if \(!config\.configured\) \{\s*setAgentTransport\(null\)/);
  assert.match(store, /agentTransport\(\)\.reset\?\.\(\)/, "clear forgets the server conversation");
});

test("the key form is write-only", () => {
  const panel = readFileSync(resolve(src, "settings/components/SettingAssistantChat.vue"), "utf-8");
  assert.match(panel, /type="password"/);
  assert.match(panel, /config\.keyHint/);
  assert.match(panel, /agent\.refreshTransport\(\)/, "saving re-installs the panel's agent");
});
