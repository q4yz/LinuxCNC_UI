<script setup>
// Dashboard macro panel. Lists every persisted macro with a "Run"
// button; "Run" parses the macro into blocks (via the JS port of
// ``backend/modules/macros/parser.py``) and dispatches each
// ``static`` block as one MDI command per non-blank line. ``python``
// blocks are surfaced to the console as warnings; the backend
// interpreter is not implemented yet.
//
// Three ``kind`` values share this panel; each row carries a kind
// tag so operators can tell the surface apart:
//
//   * ``macro`` (custom, in-repo ``.macro`` files) — Run button.
//   * ``ngc`` (LinuxCNC native subroutine) — body size + Edit only.
//   * ``mcode`` (LinuxCNC custom M-code M100..M199) — listed in
//     the sibling ``McodePanel``; this panel filters them out so
//     they don't double-render across the dashboard.
//
// ``runMacro`` is sourced from the Pinia store so the E-Stop check
// and the per-block dispatch live in one place. Buttons stay
// disabled while the store is busy or the machine is in E-Stop.

import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";

import { useMacrosStore, MACRO_KIND } from "../store.js";
import { useMachineStore } from "../../../stores/machine.js";

const store = useMacrosStore();
const machine = useMachineStore();

const { isBusy, macroFiles, ngcFiles } = storeToRefs(store);

// Per-row transient state — which macro the operator has just
// clicked and whether a dispatch is in flight. Reset when the user
// clicks again or the list refreshes.
const runningName = ref("");
const lastResult = ref(/** @type {{name: string, staticDispatched: number, pythonSkipped: number} | null} */ (null));

// Dashboard joins the per-kind ``macro`` and ``ngc`` containers.
// M-codes live in their own ``McodePanel`` (separate ref) and are
// never joined here. ``storeToRefs`` keeps each container
// reactive independently so M-code listings never clobber the
// macro / ngc rows on mount-order changes.
const sorted = computed(() =>
  [...macroFiles.value, ...ngcFiles.value].sort((a, b) =>
    a.name.localeCompare(b.name),
  ),
);

onMounted(async () => {
  // Lazily load both halves of ``<repo>/macros/`` once the
  // panel is mounted — mirrors the rest of the dashboard's "fire
  // and forget" pattern.
  await Promise.all([
    store.loadList(MACRO_KIND.MACRO),
    store.loadList(MACRO_KIND.NGC),
  ]);
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
  return Promise.all([
    store.loadList(MACRO_KIND.MACRO),
    store.loadList(MACRO_KIND.NGC),
  ]);
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
        <span class="mr-2">🧩</span> Macros &amp; NGC
      </h2>
      <div class="flex items-center gap-3">
        <span class="text-xs text-gray-400 font-mono">
          {{ sorted.length }} file{{ sorted.length === 1 ? '' : 's' }}
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
        v-for="row in sorted"
        :key="`${row.kind}:${row.name}`"
        class="flex items-center justify-between gap-4 rounded-lg border border-gray-700 bg-gray-900/60 p-3"
        :data-kind="row.kind"
      >
        <div class="min-w-0">
          <div class="font-mono text-sm font-semibold text-gray-100 truncate flex items-center gap-2">
            🧩 {{ row.name }}
            <span
              class="text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wider"
              :class="
                row.kind === 'macro'
                  ? 'bg-blue-700/40 text-blue-200'
                  : 'bg-purple-700/40 text-purple-200'
              "
            >
              {{ row.kind }}
            </span>
          </div>
          <div class="text-xs text-gray-500">
            {{ row.size_bytes }} bytes
          </div>
        </div>
        <div class="flex items-center gap-3 shrink-0">
          <!-- Run only on ``macro`` rows. NGC subroutines run via
               the controller's ``program_open`` flow, not MDI; the
               UI only manages the file content. -->
          <button
            v-if="row.kind === 'macro'"
            type="button"
            class="rounded bg-green-600 hover:bg-green-500 disabled:bg-green-900 disabled:cursor-not-allowed px-3 py-1.5 text-sm font-semibold text-white"
            :disabled="isBusy || runningName === row.name || machine.isEstopActive"
            :title="machine.isEstopActive ? 'Cannot run while in E-Stop' : 'Run macro'"
            @click="onRun(row.name)"
          >
            <span v-if="runningName === row.name">Running…</span>
            <span v-else>▶ Run</span>
          </button>
          <span
            v-else
            class="text-[10px] text-gray-500 uppercase tracking-wider"
            title="NGC subroutines run via program_open, not MDI"
          >
            edit only
          </span>
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
