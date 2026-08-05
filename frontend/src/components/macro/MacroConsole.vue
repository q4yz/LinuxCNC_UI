<script setup>
// Read-only console pane for the macro editor. Displays the
// ``logs`` vector returned by the last run plus a header with
// a Clear button. Auto-scrolls to the bottom so the operator
// sees the latest line without manual scrolling.

import { nextTick, ref, watch } from 'vue';

const props = defineProps({
  logs: { type: Array, default: () => [] },
  error: { type: String, default: '' },
  running: { type: Boolean, default: false },
});

const emit = defineEmits(['clear']);

const container = ref(null);

watch(
  () => props.logs.length,
  async () => {
    await nextTick();
    if (container.value) {
      container.value.scrollTop = container.value.scrollHeight;
    }
  }
);

function levelClass(level) {
  switch (level) {
    case 'error':
      return 'text-red-400';
    case 'warning':
      return 'text-yellow-400';
    default:
      return 'text-gray-300';
  }
}
</script>

<template>
  <div class="bg-gray-900 border-t border-gray-700 flex flex-col h-48 shrink-0">
    <header class="flex items-center justify-between px-3 py-1 border-b border-gray-700 bg-gray-800">
      <h4 class="text-xs font-semibold uppercase tracking-wider text-gray-300">
        Console
        <span v-if="running" class="ml-2 text-blue-300">Running…</span>
      </h4>
      <button
        type="button"
        class="text-xs text-gray-400 hover:text-white"
        @click="emit('clear')"
      >
        Clear
      </button>
    </header>

    <div ref="container" class="flex-1 overflow-y-auto p-2 font-mono text-xs space-y-0.5">
      <p v-if="logs.length === 0 && !error" class="text-gray-500 italic">
        Run a macro to see its log output here.
      </p>
      <p v-for="(entry, idx) in logs" :key="idx" :class="levelClass(entry.level)">
        [{{ entry.level.toUpperCase() }}] {{ entry.message }}
      </p>
      <p v-if="error" class="text-red-400 whitespace-pre-wrap">
        {{ error }}
      </p>
    </div>
  </div>
</template>
