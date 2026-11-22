// The in-app assistant as an ``AgentTransport``: Claude, run by the system
// service with the machine's MCP tools (``facades/assistantFacade.ts``).
//
// The conversation lives on the server; this keeps its id (per browser)
// and polls it while a reply streams in. Tool calls show as "-> ..." lines
// in the reply; actions that need approval appear as cards meanwhile.

import { errorStatus } from "../core/error-format";
import { assistantFacade, type AssistantConversation, type ChatEntry } from "../facades/assistantFacade";
import type { AgentTransport, ChatMessage } from "./agentChat";

export const CONVERSATION_KEY = "linuxcnc-ui.agent-conversation.v1";
/** How often a streaming reply is fetched (ms). */
export const POLL_MS = 400;

function loadId(): string | null {
  try {
    return window.localStorage.getItem(CONVERSATION_KEY);
  } catch {
    return null;
  }
}

function saveId(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(CONVERSATION_KEY, id);
    else window.localStorage.removeItem(CONVERSATION_KEY);
  } catch {
    // storage blocked: the conversation just won't survive a reload
  }
}

const TOOL_STATUS: Record<string, string> = { running: " ...", done: "", error: " (failed)" };

/** What the panel shows for one run: tool lines, texts, the streaming part. */
export function renderRun(entries: ChatEntry[], partial: string): string {
  const parts: string[] = [];
  for (const entry of entries) {
    if (entry.role === "tool") parts.push(`-> ${entry.text}${TOOL_STATUS[entry.status] ?? ""}`);
    else if (entry.role === "assistant" || entry.role === "error") parts.push(entry.text);
  }
  if (partial.trim()) parts.push(partial.trim());
  return parts.join("\n\n");
}

/** The run's entries: everything after the last user entry. */
export function runEntries(conv: AssistantConversation): ChatEntry[] {
  let start = conv.entries.length;
  for (let i = conv.entries.length - 1; i >= 0; i -= 1) {
    if (conv.entries[i].role === "user") {
      start = i + 1;
      break;
    }
  }
  return conv.entries.slice(start);
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function createBackendTransport(modelLabel: string): AgentTransport & { reset(): void } {
  let conversationId = loadId();

  async function start(text: string): Promise<{ conv: AssistantConversation; note: string }> {
    try {
      return { conv: await assistantFacade.send(text, conversationId), note: "" };
    } catch (err) {
      if (errorStatus(err) === 404 && conversationId) {
        // The system service restarted and forgot the conversation.
        conversationId = null;
        saveId(null);
        return { conv: await assistantFacade.send(text, null), note: "(Started a new conversation: the earlier one was lost when the system service restarted.)" };
      }
      if (errorStatus(err) === 412) throw new Error("No Anthropic API key is set: Settings -> Assistant.");
      throw err;
    }
  }

  return {
    name: `Claude (${modelLabel})`,
    connected: true,
    async send(history: readonly ChatMessage[], onPartial?: (text: string) => void, signal?: AbortSignal) {
      const last = history[history.length - 1];
      const { conv: first, note } = await start(last?.text ?? "");
      conversationId = first.id;
      saveId(first.id);
      let conv = first;
      let stopping = false;
      const show = (c: AssistantConversation) => [note, renderRun(runEntries(c), c.partial)].filter(Boolean).join("\n\n");
      while (conv.busy) {
        if (signal?.aborted && !stopping) {
          stopping = true;
          await assistantFacade.stop(conv.id);
        }
        onPartial?.(show(conv));
        await sleep(POLL_MS);
        conv = await assistantFacade.conversation(conv.id);
      }
      if (stopping) throw new Error("Stopped.");
      const run = runEntries(conv);
      const text = show(conv);
      // A run that produced nothing but an error is shown as a failure.
      if (run.length > 0 && run.every((e) => e.role === "error")) throw new Error(run.map((e) => e.text).join(" "));
      return { text: text || "(no answer)" };
    },
    reset() {
      if (conversationId) void assistantFacade.forget(conversationId);
      conversationId = null;
      saveId(null);
    },
  };
}
