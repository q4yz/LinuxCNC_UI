<script setup lang="ts">
// Fold-out assistant chat on the right edge.
//
// Folded: a small tab on the right edge (with a count of replies that
// came in while folded). Unfolded: a panel from below the E-stop box to
// the bottom, over the page but without a backdrop, so the machine
// stays visible and usable. The E-stop box stays on top of it (the
// panel's z-40 is below the E-stop's, see test-z-index.ts). The agent behind it is pluggable: see
// ``agent/agentChat.ts`` (``AgentTransport``).
//
// Actions the assistant asks to run (through MCP: homing, MDI, heaters …)
// appear as cards on top with Approve / Deny; a new one unfolds the panel.

import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";

import Icon from "../../ui/Icon.vue";
import AgentConfirmationCard from "./AgentConfirmationCard.vue";
import { estopBox } from "../../ui/estopClearance";
import { useAgentStore } from "../../stores/agentStore";

const agent = useAgentStore();
const { open, messages, busy, draft, unread, transportName, connected, confirmations, pending, answering } = storeToRefs(agent);
/** Ticks every second while something waits (the cards' countdown). */
const now = ref(Date.now());
let clock: ReturnType<typeof setInterval> | null = null;

const list = ref<HTMLElement | null>(null);
const input = ref<HTMLTextAreaElement | null>(null);
/** The panel starts below the E-stop box. */
const top = ref(0);

function measureTop(): void {
  top.value = Math.ceil(estopBox()?.bottom ?? 0);
}

function scrollToEnd(): void {
  void nextTick(() => {
    if (list.value) list.value.scrollTop = list.value.scrollHeight;
  });
}

watch(open, (isOpen) => {
  if (!isOpen) return;
  measureTop();
  scrollToEnd();
  void nextTick(() => input.value?.focus());
});
watch(() => messages.value.map((m) => m.text.length).join(), scrollToEnd);

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    void agent.send();
  }
}

function onWindowKey(event: KeyboardEvent): void {
  if (event.key === "Escape" && open.value) agent.toggle(false);
}

function time(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

onMounted(() => {
  void agent.refreshTransport();
  agent.startPolling();
  clock = setInterval(() => (now.value = Date.now()), 1000);
  measureTop();
  window.addEventListener("resize", measureTop);
  window.addEventListener("keydown", onWindowKey);
});
onBeforeUnmount(() => {
  agent.stopPolling();
  if (clock !== null) clearInterval(clock);
  window.removeEventListener("resize", measureTop);
  window.removeEventListener("keydown", onWindowKey);
});
</script>

<template>
  <!-- Folded: the tab on the right edge. -->
  <button
    v-show="!open"
    type="button"
    data-testid="agent-tab"
    class="fixed right-0 top-1/2 z-40 flex -translate-y-1/2 flex-col items-center gap-2 rounded-l-lg border border-r-0 border-gray-600 bg-gray-800 px-1.5 py-3 text-gray-300 hover:bg-gray-700 hover:text-white"
    aria-label="Open the assistant"
    @click="agent.toggle(true)"
  >
    <span class="relative">
      <Icon name="chat" size="h-5 w-5" />
      <span
        v-if="pending.length > 0"
        data-testid="agent-pending-badge"
        class="absolute -right-2 -top-2 rounded-full bg-amber-500 px-1 text-[10px] font-bold leading-4 text-gray-900"
      >{{ pending.length }}</span>
      <span
        v-else-if="unread > 0"
        class="absolute -right-2 -top-2 rounded-full bg-blue-600 px-1 text-[10px] font-bold leading-4 text-white"
      >{{ unread }}</span>
    </span>
    <span class="text-xs font-medium tracking-wide [writing-mode:vertical-rl]">Assistant</span>
  </button>

  <!-- Unfolded: the panel. -->
  <Transition
    enter-active-class="transition-transform duration-200 ease-out"
    leave-active-class="transition-transform duration-150 ease-in"
    enter-from-class="translate-x-full"
    leave-to-class="translate-x-full"
  >
    <aside
      v-if="open"
      data-testid="agent-panel"
      class="fixed bottom-0 right-0 z-40 flex w-full flex-col border-l border-t border-gray-700 bg-gray-800 sm:w-96"
      :style="{ top: `${top}px` }"
      aria-label="Assistant"
    >
      <header class="flex items-center gap-2 border-b border-gray-700 px-3 py-2">
        <Icon name="chat" size="h-5 w-5" class="text-blue-400" />
        <div class="min-w-0 flex-1">
          <div class="text-sm font-semibold text-gray-100">Assistant</div>
          <div class="flex items-center gap-1.5 truncate text-xs text-gray-400">
            <span class="inline-block h-2 w-2 shrink-0 rounded-full" :class="connected ? 'bg-green-500' : 'bg-gray-500'" />
            {{ transportName }}
          </div>
        </div>
        <button
          type="button"
          class="rounded p-1.5 text-gray-400 hover:bg-gray-700 hover:text-white disabled:opacity-40"
          :disabled="messages.length === 0"
          aria-label="Clear the conversation"
          title="Clear the conversation"
          @click="agent.clear()"
        >
          <Icon name="trash" size="h-4 w-4" />
        </button>
        <button
          type="button"
          data-testid="agent-fold"
          class="rounded p-1.5 text-gray-400 hover:bg-gray-700 hover:text-white"
          aria-label="Fold the assistant away"
          title="Fold away (Esc)"
          @click="agent.toggle(false)"
        >
          <Icon name="chevronLeft" size="h-4 w-4" class="rotate-180" />
        </button>
      </header>

      <div
        v-if="confirmations.length > 0"
        class="max-h-[60%] shrink-0 space-y-2 overflow-y-auto border-b border-gray-700 p-3"
        data-testid="agent-confirmations"
      >
        <AgentConfirmationCard
          v-for="item in confirmations"
          :key="item.id"
          :confirmation="item"
          :now="now"
          :busy="answering.includes(item.id)"
          @approve="agent.approve"
          @deny="agent.deny"
        />
      </div>

      <div ref="list" class="flex-1 space-y-3 overflow-y-auto px-3 py-3" data-testid="agent-messages">
        <p v-if="messages.length === 0" class="pt-6 text-center text-sm text-gray-500">
          Ask about the machine, a print, a calibration or an error.
        </p>
        <div
          v-for="message in messages"
          :key="message.id"
          class="flex flex-col"
          :class="message.role === 'user' ? 'items-end' : 'items-start'"
        >
          <div
            class="max-w-[85%] whitespace-pre-wrap break-words rounded-lg px-3 py-2 text-sm"
            :class="message.role === 'user'
              ? 'bg-blue-600 text-white'
              : message.error ? 'border border-red-700 bg-red-950 text-red-200' : 'bg-gray-700 text-gray-100'"
          >
            <template v-if="message.text">{{ message.text }}</template>
            <span v-else class="text-gray-400">…</span>
          </div>
          <span class="mt-0.5 px-1 text-[10px] text-gray-500">{{ time(message.time) }}</span>
        </div>
      </div>

      <form class="flex items-end gap-2 border-t border-gray-700 p-3" @submit.prevent="agent.send()">
        <textarea
          ref="input"
          v-model="draft"
          rows="2"
          data-testid="agent-input"
          class="max-h-40 min-h-[2.5rem] flex-1 resize-y rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-sm text-gray-100 placeholder-gray-500 focus:border-blue-500 focus:outline-none"
          placeholder="Message (Enter sends, Shift+Enter new line)"
          @keydown="onKeydown"
        />
        <button
          v-if="busy"
          type="button"
          class="rounded bg-gray-600 p-2 text-white hover:bg-gray-500"
          aria-label="Stop the reply"
          title="Stop"
          @click="agent.stop()"
        >
          <Icon name="stop" size="h-5 w-5" />
        </button>
        <button
          v-else
          type="submit"
          data-testid="agent-send"
          class="rounded bg-blue-600 p-2 text-white hover:bg-blue-500 disabled:opacity-40"
          :disabled="!draft.trim()"
          aria-label="Send"
          title="Send"
        >
          <Icon name="send" size="h-5 w-5" />
        </button>
      </form>
    </aside>
  </Transition>
</template>
