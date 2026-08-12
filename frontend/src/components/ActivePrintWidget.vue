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
//
// File list source-of-truth: ``ProgramFilesService.listFiles()``,
// the same endpoint the Files view and the editor use. The widget
// refreshes the list on mount and after every successful load. The
// ``recentFiles`` getter on the facade is the historical fallback
// (still returned for backward-compatibility consumers) but the
// widget itself reads from the live endpoint so the operator sees
// what's actually in the program root at load time.

import { computed, ref, onMounted } from "vue";
import { storeToRefs } from "pinia";
import { useMachineStore, SystemState } from "../stores/machineStore.js";
import { useBaseThreadStore } from "../stores/baseThread.js";
import {useConsoleStore} from "../stores/console.js";
import {ModulesProgramService, ProgramFilesService} from "../../generated/api/index.ts";

const store = useMachineStore();
const baseThread = useBaseThreadStore();
const consoleStore = useConsoleStore()
const { systemState, status } = storeToRefs(store);
const { progress } = storeToRefs(baseThread);

// --- File list state -----------------------------------------------------
//
// ``files`` is the canonical list of programs on the active
// backend root. Refreshed on mount and after every successful load.
// ``loadError`` carries the last fetch error so the operator
// sees *why* the list is empty (vs. just "no files yet").
const files = ref([])
const isLoadingList = ref(false)
const loadError = ref(null)

async function fetchFiles() {
  isLoadingList.value = true
  loadError.value = null
  try {
    const listing = await ProgramFilesService.listFiles()
    files.value = Array.isArray(listing) ? listing : []
  } catch (err) {
    // ``ProgramFilesService.listFiles`` returns 404 when the
    // upload root is empty or missing; treat that as "no files"
    // rather than a hard error — the empty-state UI covers it.
    const status = err?.status ?? err?.response?.status
    if (status !== 404) {
      consoleStore.error(`[ActivePrintWidget] Failed to load file list: ${err?.body?.detail || err?.message || 'unknown error'}`)
      loadError.value = err?.body?.detail || err?.message || 'unknown error'
    }
    files.value = []
  } finally {
    isLoadingList.value = false
  }
}

onMounted(() => {
  fetchFiles()
})

// --- Lifecycle state -----------------------------------------------------
//
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

// --- Loaded-file lookup --------------------------------------------------
//
// The state facade exposes ``status.file`` as the basename of the
// loaded program. The file list's ``file.filename`` uses the same
// canonical form (the value the user's Klipper config declared).
// A filename match is the canonical way to know which row in the
// list is the active program. ``isLoadedFile`` returns true when
// the row's filename matches the interpreter's loaded file.
const isLoadedFile = (filename) => {
  const loaded = status.value?.file;

  if (systemState.value === SystemState.IDLE) {
    return false;
  }

  if (typeof loaded !== "string" || loaded.length === 0 || !filename) {
    return false;
  }

  // Extract just the file name, ignoring any leading directories or slashes.
  // Example: "gcodes/my_file.gcode" becomes "my_file.gcode"
  const loadedBase = loaded.split('/').pop().split('\\').pop();
  const targetBase = filename.split('/').pop().split('\\').pop();

  return loadedBase === targetBase;
}

// --- Print-in-flight state ----------------------------------------------
//
// ``isLoading`` is True between the operator clicking Print and
// the ``loadProgram`` round-trip resolving. The Standby-view
// Print buttons bind ``:disabled="isLoading"`` so a fast
// double-click cannot fire two concurrent loads. The flag
// resets in the ``finally`` block so a failed load still
// re-enables the buttons.
const isLoading = ref(false);

// Pretty-print the progress as a one-decimal percentage so the bar
// label does not dance between ``33.3333%`` and ``33.3334%`` on
// every telemetry tick. The fraction comes straight from the
// base-thread store's getter — the store owns the divide-by-zero
// guard + clamp so this component stays a pure renderer.
const progressFraction = computed(() => baseThread.progressFraction);
const progressPercent = computed(() => progressFraction.value.toFixed(1));

// Cap the recent-files list to the five newest G-code / NGC
// entries. ``files`` is the ``FileInfo`` shape returned by
// ``ProgramFilesService.listFiles()``.
const PRINTABLE_EXTENSIONS = [".gcode", ".ngc"];

const printableFiles = computed(() => {
  if (!Array.isArray(files.value)) return [];
  return files.value
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



async function loadFile(filename) {
  if (!filename) return;

  // Guard against a double-click while the first load is still in
  // flight. The button is also bound ``:disabled="isLoading"`` so
  // the operator can't double-click, but this is a belt-and-braces
  // guard for keyboard / programmatic invocation.
  if (isLoading.value) return;

  // Guard: refuse to load only when the interpreter is actively
  // moving. ``LOADED`` is allowed — the backend's ``program_open``
  // replaces the existing file pointer, so loading a new file
  // while one is loaded is a single-click override (the operator
  // does not need to click Unload first). ``RUNNING`` and ``PAUSED``
  // are rejected because replacing the active program mid-move
  // would leave the interpreter pointing at a file the operator
  // did not request. ``ESTOP`` / ``OFFLINE`` / ``UPDATING`` /
  // ``FAILURE`` are also rejected because the backend isn't in a
  // state to accept a load.
  if (
    systemState.value === SystemState.RUNNING ||
    systemState.value === SystemState.PAUSED
  ) {
    consoleStore.error(`[ActivePrintWidget] Cannot load. Machine is currently: ${systemState.value}`);
    return;
  }

  isLoading.value = true;
  consoleStore.debug(`[ActivePrintWidget] Loading program: ${filename}`);
  try {
    // Step 1: load. The widget's reactive state transitions to
    // SystemState.LOADED on the next telemetry tick and the new
    // "Loaded" branch renders a dedicated Start button. The
    // operator must press Start explicitly so the two-step
    // lifecycle is visible (matches LinuxCNC's CLI semantics).
    await ModulesProgramService.loadProgram({ filename });
    consoleStore.success(`Loaded ${filename}. Press Start to begin.`);
    // Refresh the file list so the just-loaded file's mtime
    // reflects in the Standby view's ordering.
    await fetchFiles();
  } catch (err) {
    // The generated client throws ApiError on failure, which includes useful data.
    consoleStore.error(
      `[ActivePrintWidget] Failed to load: ${err.body?.detail || err.message}`,
      { popup: true, title: "Load failed" },
    );
  } finally {
    isLoading.value = false;
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
  // Dedicated ``POST /unload`` endpoint. The previous workaround
  // (``stopProgram``) only aborted the active move — the file
  // pointer stayed open in the firmware's memory, so the
  // state-machine facade kept reporting ``SystemState.LOADED`` and
  // the runtime highlight stayed stuck. The new endpoint clears
  // the file pointer so the next telemetry tick reports
  // ``stat.file == ""`` and the state-machine drops to pure Idle.
  consoleStore.debug("[ActivePrintWidget] Unloading program...");
  try {
    // The generated client picks up the new endpoint after a
    // ``npm run generate-api`` pass.
    await ModulesProgramService.unloadProgram();
    // No need to refresh the file list or nudge any local state —
    // the next WebSocket tick will surface ``stat.file == ""`` and the
    // computed ``systemState`` will return to Idle automatically.
    // The Load buttons across the file list re-enable because the
    // highlight is keyed on ``isLoadedFile(filename)`` which is now
    // false for every row.
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
    <!-- Top-bar: Start button. Always visible across all branches so
         the operator has a single, stable affordance for the
         "kick off the run" action. Enabled only when the interpreter
         is in the LOADED state (a program is open and idle); disabled
         otherwise. The right upper corner is intentionally empty
         because the global EStop button covers this area. -->
    <div class="p-4 border-b border-gray-700">
      <button
        type="button"
        :disabled="!isLoaded"
        @click="startLoadedProgram"
        class="w-full px-4 py-3 bg-green-600 hover:bg-green-500 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded font-semibold text-base transition-colors shadow"
      >Start</button>
    </div>

    <!-- File list: always visible across all branches. The loaded
         file is highlighted with a blue background, a soft ring,
         and a bold blue filename. Its button swaps from the blue
         "Load" affordance to a red "Unload" affordance and calls
         ``unloadProgram``. The right upper corner is intentionally
         empty (EStop covers this area; the Standby/Loaded headers
         that used to live there are gone — the file list is the
         primary UI now). -->
    <div class="p-4 border-b border-gray-700">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center mb-3">
        <span class="mr-2">📂</span> Programs
      </h2>
      <p class="text-[10px] text-gray-500 -mt-2 mb-2">
        Click <span class="font-semibold">Load</span> to queue — overrides
        the current file when the machine is in
        <span class="font-semibold">Loaded</span> state.
      </p>

      <ul v-if="printableFiles.length > 0" class="divide-y divide-gray-700/60">
        <li
          v-for="file in printableFiles"
          :key="file.filename"
          class="flex items-center justify-between py-2 gap-3 rounded px-2"
          :class="isLoadedFile(file.filename) ? 'bg-blue-900/40 ring-1 ring-blue-500/40' : ''"
        >
          <span
            class="text-sm font-mono truncate"
            :class="isLoadedFile(file.filename) ? 'text-blue-300 font-semibold' : 'text-gray-200'"
            :title="file.filename"
          >
            {{ file.filename }}
          </span>
          <button
            type="button"
            :class="isLoadedFile(file.filename)
              ? 'shrink-0 px-3 py-1 bg-red-600 hover:bg-red-500 text-white rounded text-xs font-semibold transition-colors'
              : 'shrink-0 px-3 py-1 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-900 disabled:cursor-wait text-white rounded text-xs font-semibold transition-colors'"
            :disabled="isLoading || (systemState === SystemState.RUNNING || systemState === SystemState.PAUSED)"
            @click="isLoadedFile(file.filename) ? unloadProgram() : loadFile(file.filename)"
          >
            <span v-if="isLoading && !isLoadedFile(file.filename)">Loading…</span>
            <span v-else-if="isLoadedFile(file.filename)">Unload</span>
            <span v-else>Load</span>
          </button>
        </li>
      </ul>

      <div v-else-if="isLoadingList" class="text-xs text-gray-500 italic">
        Loading program list…
      </div>
      <div v-else-if="loadError" class="text-xs text-red-400 italic">
        Failed to load program list: {{ loadError }}
      </div>
      <div v-else class="text-xs text-gray-500 italic">
        No printable G-code files found. Upload one from the Files view.
      </div>
    </div>

    <!-- Standby hint: shown when the machine is idle and no program
         is loaded. The file list above is the primary UI; this
         section is just a one-line context hint. -->
    <div
      v-if="!isActive && !isLoaded"
      class="p-4 flex flex-col space-y-2"
    >
      <p class="text-xs text-gray-500 text-center">
        Load a program to start a job.
      </p>
    </div>

    <!-- Loaded hint: shown when a program is loaded but the run
         hasn't started. The file list above already shows the loaded
         file highlighted with an Unload button; this section just
         confirms the firmware state. -->
    <div
      v-else-if="isLoaded"
      class="p-4 flex flex-col space-y-2"
    >
      <p class="text-xs text-gray-500 text-center">
        Press <span class="font-semibold text-blue-300">Start</span> above
        to begin the run.
      </p>
    </div>

    <!-- Active view: the interpreter is reading a program (or paused
         mid-program). The Start button at the top is disabled —
         the program is already running. The body shows the loaded
         filename, the progress bar, and the Pause/Resume + Stop
         buttons. The file list above still shows the loaded file
         highlighted. -->
    <div v-else class="p-4 flex flex-col space-y-4">
      <div class="flex items-center">
        <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
          <span class="mr-2">🖨️</span>
          {{ isPaused ? "Paused" : "Printing" }}
        </h2>
        <!-- Right upper corner intentionally empty: the global
             EStop button covers this area. -->
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
            :style="{ width: `${progressFraction}%` }"
          ></div>
        </div>
        <div class="flex items-center justify-between text-[10px] text-gray-500 font-mono">
          <span>Line {{ progress.current_line }}</span>
          <span>of {{ progress.total_lines || "?" }}</span>
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
