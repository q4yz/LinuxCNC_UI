<script setup>
// ActivePrintWidget — dashboard widget driven by the State Facade
// (``stores/machineStore.js``). Three visual states:
//
//   * Standby — Idle / PowerOff / Estop / Offline / Updating /
//     Failure. Shows the five newest G-code files via the facade's
//     ``recentFiles`` getter with a Print button each. Clicking
//     Print calls ``loadProgram`` (the "load" step).
//   * Loaded — A program is open in the interpreter (``stat.file``
//     set, ``interp_state`` is ``INTERP_IDLE``) but the run has
//     not started. Renders the loaded filename and a dedicated
//     Start button that calls ``runProgram``.
//   * Active — Running / Paused. Shows the loaded filename, the
//     progress bar, and Pause/Resume/Stop buttons.
//
// The widget mirrors LinuxCNC's two-step "load then start" lifecycle;
// the state facade's ``SystemState.LOADED`` member is the trigger
// for the middle branch.

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
const isLoaded = computed(() => systemState.value === SystemState.LOADED);
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

  // Guard: We can only load a new program if the interpreter is
  // idle. A running program must be stopped first; the LOADED
  // branch has its own Unload button to clear the file pointer.
  if (systemState.value !== SystemState.IDLE) {
    consoleStore.error(`[ActivePrintWidget] Cannot load. Machine is currently: ${systemState.value}`);
    return;
  }

  consoleStore.debug(`[ActivePrintWidget] Loading program: ${filename}`);
  try {
    // Step 1: load. The widget's reactive state transitions to
    // SystemState.LOADED on the next telemetry tick and the new
    // "Loaded" branch renders a dedicated Start button. The
    // operator must press Start explicitly so the two-step
    // lifecycle is visible (matches LinuxCNC's CLI semantics).
    await ModulesProgramService.loadProgram({ filename });
    consoleStore.success(`Loaded ${filename}. Press Start to begin.`);
  } catch (err) {
    // The generated client throws ApiError on failure, which includes useful data
    consoleStore.error(`[ActivePrintWidget] Failed to load: ${err.body?.detail || err.message}`);
  }
}

async function startLoadedProgram() {
  // Guard: only start from the LOADED branch. Reaching this handler
  // from any other state is a programming error in the parent
  // component (the button is only rendered on LOADED).
  if (systemState.value !== SystemState.LOADED) {
    consoleStore.error(`[ActivePrintWidget] Ignored start: Machine is ${systemState.value}, not Loaded.`);
    return;
  }
  consoleStore.debug("[ActivePrintWidget] Requesting start...");
  try {
    await ModulesProgramService.runProgram();
  } catch (err) {
    consoleStore.error(`[ActivePrintWidget] Failed to start: ${err.body?.detail || err.message}`);
  }
}

async function unloadProgram() {
  // There is no dedicated ``/unload`` endpoint today; the closest
  // semantic is ``stopProgram`` which clears ``current_line`` and
  // puts ``interp_state`` back to ``INTERP_IDLE``. The file
  // pointer is reset by the next ``POST /load`` anyway, so the
  // operator lands in the Standby view and can pick a new file.
  consoleStore.debug("[ActivePrintWidget] Unloading program...");
  try {
    await ModulesProgramService.stopProgram();
  } catch (err) {
    consoleStore.error(`[ActivePrintWidget] Failed to unload: ${err.body?.detail || err.message}`);
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

    <!-- Loaded view: a program is open in the interpreter
         (``stat.file`` set, ``interp_state`` is ``INTERP_IDLE``)
         but the run has not started. Renders the loaded filename
         and a dedicated Start button that calls ``runProgram``.
         The operator gets a chance to verify the file before
         pressing Start — this mirrors LinuxCNC's two-step
         "program_open then auto(AUTO_RUN)" lifecycle. -->
    <div v-else-if="isLoaded" class="p-4 flex flex-col space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
          <span class="mr-2">📄</span> Loaded
        </h2>
        <span class="text-xs font-mono px-2 py-0.5 rounded bg-blue-700/40 text-blue-200">
          LOADED
        </span>
      </div>

      <div class="text-sm text-gray-200 font-mono truncate" :title="status.file">
        {{ status.file || "(unknown file)" }}
      </div>

      <div class="flex items-center gap-2 pt-2">
        <button
          type="button"
          class="flex-1 px-3 py-2 bg-green-600 hover:bg-green-500 text-white rounded font-semibold text-sm transition-colors"
          @click="startLoadedProgram"
        >Start</button>
        <button
          type="button"
          class="flex-1 px-3 py-2 bg-gray-600 hover:bg-gray-500 text-white rounded font-semibold text-sm transition-colors"
          @click="unloadProgram"
        >Unload</button>
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