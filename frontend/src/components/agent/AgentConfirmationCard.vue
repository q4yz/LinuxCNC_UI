<script setup lang="ts">
// One action the assistant wants to run: what it is, the exact request,
// and Approve / Deny. Decided ones (kept ~30 s by the backend) show their
// outcome instead of the buttons.

import { computed, ref } from "vue";

import type { AgentConfirmation } from "../../facades/agentConfirmationsFacade";

const props = defineProps<{
  confirmation: AgentConfirmation;
  /** Epoch ms, ticking (for the countdown). */
  now: number;
  busy: boolean;
}>();

const emit = defineEmits<{ approve: [id: string]; deny: [id: string, reason: string] }>();

const reason = ref("");
const showReason = ref(false);

const secondsLeft = computed(() => Math.max(0, Math.ceil((props.confirmation.expires - props.now) / 1000)));
const pending = computed(() => props.confirmation.decision === "pending");
const args = computed(() => {
  const value = props.confirmation.arguments;
  return value && Object.keys(value).length > 0 ? JSON.stringify(value, null, 2) : "";
});
const OUTCOME: Record<string, string> = {
  approved: "Approved, sent to the machine",
  denied: "Denied",
  expired: "Expired, nothing was done",
};

function deny(): void {
  if (!showReason.value) {
    showReason.value = true;
    return;
  }
  emit("deny", props.confirmation.id, reason.value.trim());
}
</script>

<template>
  <div
    data-testid="agent-confirmation"
    class="rounded-lg border p-3 text-sm"
    :class="pending ? 'border-amber-500 bg-amber-950/40' : 'border-gray-700 bg-gray-900/60 opacity-70'"
  >
    <div class="flex items-start justify-between gap-2">
      <div class="min-w-0">
        <div class="text-xs font-semibold uppercase tracking-wide" :class="pending ? 'text-amber-400' : 'text-gray-400'">
          The assistant wants to
        </div>
        <div class="font-medium text-gray-100">{{ confirmation.summary }}</div>
      </div>
      <span v-if="pending" class="shrink-0 font-mono text-xs text-amber-300" title="Expires unanswered">{{ secondsLeft }} s</span>
    </div>

    <div class="mt-2 break-all font-mono text-xs text-gray-300">
      <span class="font-semibold">{{ confirmation.method }}</span> {{ confirmation.path }}
    </div>
    <pre
      v-if="args"
      class="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded bg-gray-950 p-2 font-mono text-xs text-gray-200"
    >{{ args }}</pre>
    <div class="mt-1 text-[11px] text-gray-500">needs {{ confirmation.permission }}</div>

    <template v-if="pending">
      <input
        v-if="showReason"
        v-model="reason"
        type="text"
        data-testid="agent-deny-reason"
        class="mt-2 w-full rounded border border-gray-600 bg-gray-900 px-2 py-1 text-xs text-gray-100 placeholder-gray-500 focus:border-amber-500 focus:outline-none"
        placeholder="Why not? (optional, told to the assistant)"
        @keydown.enter.prevent="deny"
      />
      <div class="mt-2 flex gap-2">
        <button
          type="button"
          data-testid="agent-approve"
          class="flex-1 rounded bg-green-700 px-3 py-1.5 font-semibold text-white hover:bg-green-600 disabled:opacity-50"
          :disabled="busy"
          @click="emit('approve', confirmation.id)"
        >
          Approve
        </button>
        <button
          type="button"
          data-testid="agent-deny"
          class="flex-1 rounded bg-gray-700 px-3 py-1.5 font-semibold text-white hover:bg-red-700 disabled:opacity-50"
          :disabled="busy"
          @click="deny"
        >
          {{ showReason ? "Deny" : "Deny…" }}
        </button>
      </div>
    </template>
    <div v-else class="mt-2 text-xs font-medium" :class="confirmation.decision === 'approved' ? 'text-green-400' : 'text-gray-400'">
      {{ OUTCOME[confirmation.decision] }}<template v-if="confirmation.reason">: {{ confirmation.reason }}</template>
    </div>
  </div>
</template>
