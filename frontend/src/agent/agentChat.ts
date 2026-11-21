// The assistant chat: messages, the agent transport, history storage.
//
// Framework-free so it is unit-testable; ``stores/agentStore.ts`` wraps
// it for the UI. The agent itself does not exist yet: the chat talks to
// an ``AgentTransport``, and until one is installed
// (``setAgentTransport``) the offline transport answers that no agent
// is connected. A later agent (an LLM behind the backend, using the
// machine through MCP tools) only has to implement ``AgentTransport``.

export type ChatRole = "user" | "assistant" | "system";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  /** ISO time. */
  time: string;
  /** The reply failed (shown in red, not sent back as context). */
  error?: boolean;
}

export interface AgentReply {
  text: string;
}

export interface AgentTransport {
  /** Shown in the panel header ("No agent connected", a model name). */
  readonly name: string;
  readonly connected: boolean;
  /**
   * Answer the conversation. ``history`` is every earlier message,
   * oldest first, the last one being the user's new message.
   * ``onPartial`` streams the reply text so far, if the agent streams.
   */
  send(history: readonly ChatMessage[], onPartial?: (text: string) => void, signal?: AbortSignal): Promise<AgentReply>;
  /** Forget the conversation (the panel's "clear"), if the agent keeps one. */
  reset?(): void;
}

export const OFFLINE_REPLY =
  "No assistant is set up yet. Add an Anthropic API key in Settings -> Assistant and I can answer and help with the machine.";

export const offlineTransport: AgentTransport = {
  name: "Not set up (Settings -> Assistant)",
  connected: false,
  async send() {
    return { text: OFFLINE_REPLY };
  },
};

let transport: AgentTransport = offlineTransport;
const listeners = new Set<(t: AgentTransport) => void>();

export function setAgentTransport(next: AgentTransport | null): void {
  transport = next ?? offlineTransport;
  listeners.forEach((listener) => listener(transport));
}

/** Called whenever the transport changes; returns the unsubscribe. */
export function onAgentTransport(listener: (t: AgentTransport) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function agentTransport(): AgentTransport {
  return transport;
}

let counter = 0;

export function newMessage(role: ChatRole, text: string, extra: Partial<ChatMessage> = {}): ChatMessage {
  counter += 1;
  return { id: `${Date.now().toString(36)}-${counter}`, role, text, time: new Date().toISOString(), ...extra };
}

/** What goes to the agent: the conversation without failed replies. */
export function contextFor(messages: readonly ChatMessage[]): ChatMessage[] {
  return messages.filter((m) => !m.error && m.role !== "system");
}

// -- history (per browser, a convenience: not the agent's memory) -------- //

export const HISTORY_KEY = "linuxcnc-ui.agent-chat.v1";
/** Messages kept in the browser. */
export const MAX_HISTORY = 200;

export interface KeyValueStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function browserStore(): KeyValueStore | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

function isMessage(value: unknown): value is ChatMessage {
  const m = value as ChatMessage;
  return (
    !!m && typeof m === "object" && typeof m.id === "string" && typeof m.text === "string" &&
    typeof m.time === "string" && (m.role === "user" || m.role === "assistant" || m.role === "system")
  );
}

export function loadHistory(store: KeyValueStore | null = browserStore()): ChatMessage[] {
  try {
    const raw = store?.getItem(HISTORY_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter(isMessage).slice(-MAX_HISTORY) : [];
  } catch {
    return [];
  }
}

export function saveHistory(messages: readonly ChatMessage[], store: KeyValueStore | null = browserStore()): void {
  try {
    if (messages.length === 0) store?.removeItem(HISTORY_KEY);
    else store?.setItem(HISTORY_KEY, JSON.stringify(messages.slice(-MAX_HISTORY)));
  } catch {
    // Private window / full storage: the chat still works, unsaved.
  }
}
