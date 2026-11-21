import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";

import { agentConfirmationsFacade, type AgentConfirmation } from "../facades/agentConfirmationsFacade";
import { useConsoleStore } from "./console";
import {
  agentTransport,
  contextFor,
  loadHistory,
  newMessage,
  saveHistory,
  type ChatMessage,
} from "../agent/agentChat";

/** How often the panel asks for the assistant's pending actions (ms). */
export const CONFIRMATION_POLL_MS = 2000;

/** The assistant chat panel: open state, the conversation, sending, and
 * the assistant's actions waiting for the operator's approval. */
export const useAgentStore = defineStore("agent", () => {
  const open = ref(false);
  const messages = ref<ChatMessage[]>(loadHistory());
  const busy = ref(false);
  /** Text typed but not sent yet (kept while the panel is folded). */
  const draft = ref("");
  /** Assistant messages arrived while the panel was closed. */
  const unread = ref(0);
  let abort: AbortController | null = null;
  /** The assistant's actions: pending ones, and the last decided. */
  const confirmations = ref<AgentConfirmation[]>([]);
  const pending = computed(() => confirmations.value.filter((c) => c.decision === "pending"));
  /** Ids being answered right now (buttons disabled). */
  const answering = ref<string[]>([]);
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let polling = false;
  const seen = new Set<string>();

  const transportName = computed(() => agentTransport().name);
  const connected = computed(() => agentTransport().connected);

  watch(messages, (next) => saveHistory(next), { deep: true });
  watch(open, (isOpen) => {
    if (isOpen) unread.value = 0;
  });

  function toggle(next?: boolean): void {
    open.value = next ?? !open.value;
  }

  async function send(text: string = draft.value): Promise<void> {
    const content = text.trim();
    if (!content || busy.value) return;
    draft.value = "";
    messages.value.push(newMessage("user", content));
    const reply = newMessage("assistant", "");
    messages.value.push(reply);
    const index = messages.value.length - 1;
    const update = (patch: Partial<ChatMessage>) => {
      messages.value[index] = { ...messages.value[index], ...patch };
    };
    busy.value = true;
    abort = new AbortController();
    try {
      const history = contextFor(messages.value.slice(0, -1));
      const answer = await agentTransport().send(history, (partial) => update({ text: partial }), abort.signal);
      update({ text: answer.text });
    } catch (err) {
      const aborted = abort?.signal.aborted;
      update({ text: aborted ? "Stopped." : `The assistant failed: ${err instanceof Error ? err.message : String(err)}`, error: true });
    } finally {
      busy.value = false;
      abort = null;
      if (!open.value) unread.value += 1;
    }
  }

  function stop(): void {
    abort?.abort();
  }

  function clear(): void {
    if (busy.value) stop();
    messages.value = [];
  }

  async function refreshConfirmations(): Promise<void> {
    try {
      confirmations.value = await agentConfirmationsFacade.list();
    } catch {
      return; // system service unreachable: keep the last list
    }
    // A new request unfolds the panel: the operator must see it.
    const fresh = pending.value.filter((c) => !seen.has(c.id));
    fresh.forEach((c) => seen.add(c.id));
    if (fresh.length > 0) open.value = true;
  }

  function startPolling(): void {
    if (polling) return;
    polling = true;
    const tick = async () => {
      await refreshConfirmations();
      if (polling) pollTimer = setTimeout(tick, CONFIRMATION_POLL_MS);
    };
    void tick();
  }

  function stopPolling(): void {
    polling = false;
    if (pollTimer !== null) clearTimeout(pollTimer);
    pollTimer = null;
  }

  async function answer(id: string, approve: boolean, reason = ""): Promise<void> {
    if (answering.value.includes(id)) return;
    answering.value = [...answering.value, id];
    const item = confirmations.value.find((c) => c.id === id);
    try {
      const result = approve ? await agentConfirmationsFacade.approve(id, reason) : await agentConfirmationsFacade.deny(id, reason);
      const what = item ? `${item.summary} (${item.method} ${item.path})` : id;
      const console = useConsoleStore();
      if (result.ok) console.info(`Assistant: ${approve ? "approved" : "denied"} ${what}`);
      else console.error(`Assistant: could not ${approve ? "approve" : "deny"} ${what}: ${result.failureReason ?? ""}`);
      await refreshConfirmations();
    } finally {
      answering.value = answering.value.filter((x) => x !== id);
    }
  }

  return {
    open, messages, busy, draft, unread, transportName, connected, toggle, send, stop, clear,
    confirmations, pending, answering, refreshConfirmations, startPolling, stopPolling,
    approve: (id: string) => answer(id, true),
    deny: (id: string, reason = "") => answer(id, false, reason),
  };
});
