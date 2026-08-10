<script setup>
// Dashboard macro panel. Lists every persisted macro with a "Run"
// button; "Run" parses the macro into blocks (via the JS port of
// ``backend/modules/macros/parser.py``) and dispatches each
// ``static`` block as one MDI command per non-blank line. ``python``
// blocks are surfaced to the console as warnings; the backend
// interpreter is not implemented yet.
//
// ``runMacro`` is sourced from the Pinia store so the E-Stop check
// and the per-block dispatch live in one place. The buttons stay
// disabled while the store is busy or the machine is in E-Stop.

import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";

import { useMacrosStore } from "../store.js";
import { useMachineStore } from "../../../stores/machine-compat.js";

const store = useMacrosStore();
const machine = useMachineStore();

const { macros, isBusy } = storeToRefs(store);

// Per-row transient state — which macro the operator has just
// clicked and whether a dispatch is in flight. Reset when the user
// clicks again or the list refreshes.
const runningName = ref("");
const lastResult = ref(/** @type {{name: string, staticDispatched: number, pythonSkipped: number} | null} */ (null));

const sorted = computed(() => [...macros.value]);

onMounted(async () => {
  // Lazily load once the panel is mounted — mirrors the rest of
  // the dashboard's "fire and forget; show skeletons" pattern.
  await store.loadList();
});

async function onRun(name) {
  runningName.value = name;
  try {
    const result = await store.runMacro(name);
    lastResult.value = { name, ...result };
  } finally {
    runningName.value = "";
  }
}

function onRefresh() {
  return store.loadList();
}

function formatResult(entry) {
  if (!entry) return "";
  const pythonNote = entry.pythonSkipped
    ? `, ${entry.pythonSkipped} python block(s) skipped`
    : "";
  return `${entry.name}: ${entry.staticDispatched} command(s) sent${pythonNote}`;
}
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden">
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex justify-between items-center">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        <span class="mr-2">🧩</span> Macros
      </h2>
      <div class="flex items-center gap-3">
        <span class="text-xs text-gray-400 font-mono">
          {{ sorted.length }} macro{{ sorted.length === 1 ? '' : 's' }}
        </span>
        <button
          type="button"
          class="px-2 py-1 text-xs rounded bg-gray-600 hover:bg-gray-500 text-white disabled:opacity-50"
          :disabled="isBusy"
          @click="onRefresh"
        >
          ↻ Refresh
        </button>
      </div>
    </div>

    <div v-if="sorted.length === 0" class="p-6 text-center text-gray-500 text-sm">
      <p>No macros yet.</p>
      <p class="mt-1 text-xs text-gray-600">
        Add one in <span class="font-mono">Machine Config</span> → <span class="font-mono">Macros</span>.
      </p>
    </div>

    <ul v-else class="p-3 space-y-2">
      <li
        v-for="name in sorted"
        :key="name"
        class="flex items-center justify-between gap-4 rounded-lg border border-gray-700 bg-gray-900/60 p-3"
      >
        <div class="min-w-0">
          <div class="font-mono text-sm font-semibold text-gray-100 truncate flex items-center gap-2">
            🧩 {{ name }}
            <span class="text-[10px] text-gray-500 uppercase tracking-wider">.macro</span>
          </div>
        </div>
        <div class="flex items-center gap-3 shrink-0">
          <button
            type="button"
            class="rounded bg-green-600 hover:bg-green-500 disabled:bg-green-900 disabled:cursor-not-allowed px-3 py-1.5 text-sm font-semibold text-white"
            :disabled="isBusy || runningName === name || machine.isEstopActive"
            :title="machine.isEstopActive ? 'Cannot run while in E-Stop' : 'Run macro'"
            @click="onRun(name)"
          >
            <span v-if="runningName === name">Running…</span>
            <span v-else>▶ Run</span>
          </button>
        </div>
      </li>
    </ul>

    <div
      v-if="lastResult"
      class="px-3 py-2 border-t border-gray-700 text-[11px] text-gray-400 font-mono"
      data-test="macro-last-result"
    >
      {{ formatResult(lastResult) }}
    </div>
  </div>
</template>
