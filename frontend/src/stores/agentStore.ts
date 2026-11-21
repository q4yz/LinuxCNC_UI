import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";

import {
  agentTransport,
  contextFor,
  loadHistory,
  newMessage,
  saveHistory,
  type ChatMessage,
} from "../agent/agentChat";

/** The assistant chat panel: open state, the conversation, sending. */
export const useAgentStore = defineStore("agent", () => {
  const open = ref(false);
  const messages = ref<ChatMessage[]>(loadHistory());
  const busy = ref(false);
  /** Text typed but not sent yet (kept while the panel is folded). */
  const draft = ref("");
  /** Assistant messages arrived while the panel was closed. */
  const unread = ref(0);
  let abort: AbortController | null = null;

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

  return { open, messages, busy, draft, unread, transportName, connected, toggle, send, stop, clear };
});
