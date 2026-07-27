<script setup>
// ActivePrintWidget — dashboard widget that surfaces the current machine
// run state through the Issue #60 State Facade store.
//
// Two visual states are driven by ``store.systemState``:
//
//   * Standby — ``Idle`` / ``PowerOff`` / ``Estop`` (and the safety
//     fallbacks ``Offline`` / ``Updating`` / ``Failure``). Shows the
//     five most recent G-code files via the facade's ``recentFiles``
//     getter (mocked for now per the issue) and a "Print" button next
//     to each entry.
//
//   * Active — ``Running`` / ``Paused``. Shows the loaded filename, a
//     progress bar bound to ``store.printProgress``, and Pause/Resume
//     and Stop buttons.
//
// Click handlers are intentionally mocked with ``console.log`` per the
// issue: "Do not manually change the state; the backend will update
// the JSON automatically." The real Pinia actions still exist on the
// machine module store and a follow-up can swap the mocks for the
// actual ``startProgram`` / ``pauseProgram`` / ``resumeProgram`` /
// ``abortProgram`` calls without touching the widget's structure.

import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useMachineStore, SystemState } from "../stores/machineStore.js";

// Bind to the facade store. ``storeToRefs`` keeps ``systemState``,
// ``printProgress`` and the raw ``status`` reactive when destructured
// into the template.
const store = useMachineStore();
const { systemState, printProgress, status, recentFiles } = storeToRefs(store);

// ---------------------------------------------------------------------- //
// Visual state selection                                                 //
// ---------------------------------------------------------------------- //
//
// ``isActive`` is true only for the two "active" enum members —
// ``Running`` and ``Paused``. Anything else (``Idle``,
// ``PowerOff``, ``Estop``, ``Offline``, ``Updating``, ``Failure``)
// renders the Standby view. This intentionally diverges from the
// previous ``isPrinting`` / ``isPaused`` logic so the widget is
// driven by the facade, not by raw task/interp flags.

const isActive = computed(
  () =>
    systemState.value === SystemState.RUNNING ||
    systemState.value === SystemState.PAUSED,
);
const isPaused = computed(() => systemState.value === SystemState.PAUSED);
const isRunning = computed(() => systemState.value === SystemState.RUNNING);

// Pretty-print the progress as a one-decimal percentage so the bar
// label does not dance between ``33.3333%`` and ``33.3334%`` on
// every telemetry tick.
const progressPercent = computed(() => printProgress.value.toFixed(1));

// Filter + cap the recent-files list to the five newest G-code / NGC
// entries. ``recentFiles`` is a mocked getter on the facade; the
// shape matches ``FileInfo`` so the real ``NcFilesService.listFiles``
// call can drop in later without changes here.
const PRINTABLE_EXTENSIONS = [".gcode", ".ngc"];

const printableFiles = computed(() => {
  if (!Array.isArray(recentFiles.value)) return [];
  return recentFiles.value
    .filter((entry) => {
      if (!entry || typeof entry.filename !== "string") return false;
      const lowered = entry.filename.toLowerCase();
      return PRINTABLE_EXTENSIONS.some((ext) => lowered.endsWith(ext));
    })
    .slice()
    .sort((a, b) => {
      const aTime = Date.parse(a.modified || "") || 0;
      const bTime = Date.parse(b.modified || "") || 0;
      return bTime - aTime;
    })
    .slice(0, 5);
});

// ---------------------------------------------------------------------- //
// Mocked click handlers                                                  //
// ---------------------------------------------------------------------- //
//
// Per the issue spec. The backend's telemetry stream is the source of
// truth — the widget never mutates local state directly. A follow-up
// can replace these ``console.log`` calls with the real Pinia actions
// (``store.startProgram(filename)``, etc.) once the backend's
// file-load contract is finalised.

function printFile(filename) {
  if (!filename) return;
  // eslint-disable-next-line no-console
  console.log("[ActivePrintWidget] Print action (mocked)", filename);
}

function pausePrint() {
  // eslint-disable-next-line no-console
  console.log("[ActivePrintWidget] Pause action (mocked)");
}

function resumePrint() {
  // eslint-disable-next-line no-console
  console.log("[ActivePrintWidget] Resume action (mocked)");
}

function stopPrint() {
  // eslint-disable-next-line no-console
  console.log("[ActivePrintWidget] Stop action (mocked)");
}
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl flex flex-col">
    <!-- Standby view: the machine is not actively reading a program. -->
    <div
      v-if="!isActive"
      class="p-4 flex flex-col space-y-4"
    >
      <div class="flex items-center justify-between">
        <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
          <span class="mr-2">💤</span> Standby
        </h2>
        <span
          class="text-xs font-mono px-2 py-0.5 rounded"
          :class="systemState === SystemState.ESTOP
            ? 'bg-red-700/40 text-red-200'
            : systemState === SystemState.OFFLINE
              ? 'bg-gray-700/40 text-gray-300'
              : 'bg-blue-700/40 text-blue-200'"
        >
          {{ systemState }}
        </span>
      </div>

      <p class="text-xs text-gray-500">
        No active print. Pick one of the recent files to start a job.
      </p>

      <ul v-if="printableFiles.length > 0" class="divide-y divide-gray-700/60">
        <li
          v-for="file in printableFiles"
          :key="file.filename"
          class="flex items-center justify-between py-2 gap-3"
        >
          <span
            class="text-sm text-gray-200 font-mono truncate"
            :title="file.filename"
          >
            {{ file.filename }}
          </span>
          <button
            type="button"
            class="shrink-0 px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-semibold transition-colors"
            @click="printFile(file.filename)"
          >
            Print
          </button>
        </li>
      </ul>

      <div v-else class="text-xs text-gray-500 italic">
        No printable G-code files found. Upload one from the Files view.
      </div>
    </div>

    <!-- Active view: the interpreter is reading a program (or paused
         mid-program). The widget stays mounted across the
         Running/Paused transition — only the header chip and the
         action button label change so the layout does not jump. -->
    <div v-else class="p-4 flex flex-col space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
          <span class="mr-2">🖨️</span>
          {{ isPaused ? "Paused" : "Printing" }}
        </h2>
        <span
          class="text-xs font-mono px-2 py-0.5 rounded"
          :class="isPaused
            ? 'bg-yellow-700/40 text-yellow-200'
            : 'bg-green-700/40 text-green-200'"
        >
          {{ isPaused ? "PAUSED" : "RUNNING" }}
        </span>
      </div>

      <div class="text-sm text-gray-200 font-mono truncate" :title="status.file">
        {{ status.file || "(unknown file)" }}
      </div>

      <div class="space-y-2">
        <div class="flex items-center justify-between text-xs text-gray-400">
          <span>Progress</span>
          <span class="font-mono">{{ progressPercent }}%</span>
        </div>
        <div class="w-full h-3 bg-gray-900 rounded overflow-hidden border border-gray-700">
          <div
            class="h-full transition-all duration-300"
            :class="isPaused ? 'bg-yellow-500' : 'bg-blue-500'"
            :style="{ width: `${printProgress}%` }"
          ></div>
        </div>
        <div class="flex items-center justify-between text-[10px] text-gray-500 font-mono">
          <span>Line {{ status.current_line }}</span>
          <span>of {{ status.total_lines || "?" }}</span>
        </div>
      </div>

      <div class="flex items-center gap-2 pt-2">
        <button
          type="button"
          class="flex-1 px-3 py-2 rounded font-semibold text-sm transition-colors"
          :class="isPaused
            ? 'bg-green-600 hover:bg-green-500 text-white'
            : 'bg-yellow-600 hover:bg-yellow-500 text-white'"
          @click="isPaused ? resumePrint() : pausePrint()"
        >
          {{ isPaused ? "Resume" : "Pause" }}
        </button>
        <button
          type="button"
          class="flex-1 px-3 py-2 bg-red-600 hover:bg-red-500 text-white rounded font-semibold text-sm transition-colors"
          @click="stopPrint"
        >
          Stop / Cancel
        </button>
      </div>

      <!-- Defensive: the raw ``status.file`` can be empty during the
           first telemetry tick. ``isRunning`` is also exported from
           the script block so it is available even if a future
           refactor drops ``isPaused``. -->
      <span v-if="!isRunning && !isPaused" class="text-xs text-gray-500 italic">
        Program loaded but not yet running.
      </span>
    </div>
  </div>
</template>