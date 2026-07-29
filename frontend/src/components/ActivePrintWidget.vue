<script setup>
// ActivePrintWidget — dashboard widget driven by the State Facade
// (``stores/machineStore.js``). Two visual states:
//
//   * Standby — Idle / PowerOff / Estop / Offline / Updating /
//     Failure. Shows the five newest G-code files via the facade's
//     ``recentFiles`` getter with a Print button each.
//   * Active — Running / Paused. Shows the loaded filename, the
//     progress bar, and Pause/Resume/Stop buttons.
//
// Click handlers are mocked until a follow-up wires them to the
// machine module's actions. See ``.agent/STATE.md`` § 6.

import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useMachineStore, SystemState } from "../stores/machineStore.js";
import {useConsoleStore} from "../stores/console.js";
import {ModulesProgramService} from "../../generated/api/index.ts";

const store = useMachineStore();
const consoleStore = useConsoleStore()
const { systemState, printProgress, status, recentFiles } = storeToRefs(store);

// True only for the two active enum members; everything else
// renders the Standby view.
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

// Cap the recent-files list to the five newest G-code / NGC
// entries. ``recentFiles`` is a mocked getter on the facade; the
// shape matches ``FileInfo`` so the real ``ModulesProgramService.listFiles``
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



async function printFile(filename) {
  if (!filename) return;

  // Guard: We can only start a print if the machine is fully IDLE.
  if (systemState.value !== SystemState.IDLE) {
    consoleStore.error(`[ActivePrintWidget] Cannot start print. Machine is currently: ${systemState.value}`);
    return;
  }

  consoleStore.debug(`[ActivePrintWidget] Requesting print start for: ${filename}`);
  try {
    // 1. The OpenAPI spec for `runProgram` implies the file must be loaded first.
    // If your backend requires explicit loading, call your file/load service here:
    // await ModulesFilesService.loadFile(filename);

    // 2. Start the loaded program
    await ModulesProgramService.runProgram();
  } catch (err) {
    // The generated client throws ApiError on failure, which includes useful data
    consoleStore.error(`[ActivePrintWidget] Failed to start print: ${err.body?.detail || err.message}`);
  }
}

async function pausePrint() {
  // Guard: Only allow pause if the machine is actively moving/running
  if (systemState.value !== SystemState.RUNNING) {
    consoleStore.error("[ActivePrintWidget] Ignored pause request: Machine is not running.");
    return;
  }

  consoleStore.debug("[ActivePrintWidget] Requesting pause...");
  try {
    await ModulesProgramService.pauseProgram();
  } catch (err) {
    consoleStore.error(`[ActivePrintWidget] Failed to pause: ${err.body?.detail || err.message}`);
  }
}

async function resumePrint() {
  // Guard: Only allow resume if the machine is actually paused
  if (systemState.value !== SystemState.PAUSED) {
    consoleStore.error("[ActivePrintWidget] Ignored resume request: Machine is not paused.");
    return;
  }

  consoleStore.debug("[ActivePrintWidget] Requesting resume...");
  try {
    await ModulesProgramService.resumeProgram();
  } catch (err) {
    consoleStore.error(`[ActivePrintWidget] Failed to resume: ${err.body?.detail || err.message}`);
  }
}

async function stopPrint() {
  // Guard: Stop is only valid if a program is active (running or paused)
  if (systemState.value !== SystemState.RUNNING && systemState.value !== SystemState.PAUSED) {
    consoleStore.error("[ActivePrintWidget] Ignored stop request: No active program to stop.");
    return;
  }

  consoleStore.debug("[ActivePrintWidget] Requesting abort/stop...");
  try {
    await ModulesProgramService.stopProgram();
  } catch (err) {
    consoleStore.error(`[ActivePrintWidget] Failed to stop print: ${err.body?.detail || err.message}`);
  }
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