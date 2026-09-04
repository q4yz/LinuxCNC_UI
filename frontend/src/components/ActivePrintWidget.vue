<script setup lang="ts">
// ActivePrintWidget — dashboard widget driven by the State Facade
// (`stores/stateFacade.js`). Three visual states:
//
//   * Standby — Idle / PowerOff / Estop / Offline / Updating /
//     Failure. Shows the five newest G-code files. Clicking
//     Print calls `loadProgram` (the "load" step).
//   * Loaded — A program is open in the interpreter but the run has
//     not started. Renders the loaded filename and a dedicated
//     Start button that calls `runProgram`.
//   * Active — Running / Paused. Shows the loaded filename, the
//     progress bar, and Pause/Resume/Stop buttons.
//
// All write actions route directly through ``progressFacade`` — the
// state facade ``useMachineStore`` exposes the high-resolution
// ``systemState`` getter (Offline / Updating / Estop / PowerOff /
// Idle / Loaded / Running / Paused / Failure) but no lifecycle
// actions, so calling its methods would throw ``is not a function``.
// Failures are routed through ``reportCommandFailure`` so the
// console row + toast are uniform across every manual trigger.

import {computed, ref, shallowRef, onMounted, onBeforeUnmount, watch} from "vue";
import {storeToRefs} from "pinia";
import {useMachineStore, SystemState} from "../stores/stateFacade";
import {useBaseThreadStore} from "../stores/baseThread";
import {useConsoleStore} from "../stores/console";
import {progressFacade} from "../facades/progressFacade";
import {reportCommandFailure, describeErrorOr} from "../core/error-format";
import {ProgramFile} from "../entities/progress";
import {BaseButton} from "../ui/index.ts";
import BaseCard from "../ui/BaseCard.vue";


const facade = useMachineStore();
const baseThread = useBaseThreadStore();
const consoleStore = useConsoleStore();
const {systemState, status} = storeToRefs(facade);
const {progress} = storeToRefs(baseThread);

// --- File list state -----------------------------------------------------
//
// `files` is the canonical list of programs on the active
// backend root. Refreshed on mount and after every successful load.
// ``shallowRef`` — entities are immutable snapshots and ``ref``'s
// deep ``UnwrapRef`` would strip the ``ProgramFile`` class privates.
const files = shallowRef<ProgramFile[]>([]);
const isLoadingList = ref<boolean>(false);
const loadError = ref<string | null>(null);

async function fetchFiles() {
  isLoadingList.value = true;
  loadError.value = null;
  try {
    const listing = await progressFacade.listProgramFiles();
    files.value = Array.isArray(listing) ? listing : [];
  } catch (err: unknown) {
    const detail = describeErrorOr(err, "unknown error");
    consoleStore.error(`[ActivePrintWidget] Failed to load file list: ${detail}`);
    loadError.value = detail;
    files.value = [];
  } finally {
    isLoadingList.value = false;
  }
}

onMounted(() => {
  fetchFiles();
  remainingTimerId = setInterval(() => {
    // Reading the computed inside the interval forces Vue to
    // re-evaluate the next time the template touches it. The
    // interval is the trigger that pushes a fresh ``Date.now()`` into
    // the system; the computed reads it on demand.
    void remainingMs.value;
  }, 1000);
});

onBeforeUnmount(() => {
  if (remainingTimerId) clearInterval(remainingTimerId);
});

// --- Lifecycle state -----------------------------------------------------
const isActive = computed(
    () =>
        systemState.value === SystemState.RUNNING ||
        systemState.value === SystemState.PAUSED,
);
const isLoaded = computed(() => systemState.value === SystemState.LOADED);
const isPaused = computed(() => systemState.value === SystemState.PAUSED);
const isRunning = computed(() => systemState.value === SystemState.RUNNING);

// --- Loaded-file lookup --------------------------------------------------
const isLoadedFile = (filename: string | undefined): boolean => {
  const loaded = status.value?.file;

  if (systemState.value === SystemState.IDLE) {
    return false;
  }

  if (typeof loaded !== "string" || loaded.length === 0 || !filename) {
    return false;
  }

  // Extract just the file name, ignoring any leading directories or slashes.
  const loadedBase = loaded.split('/').pop()?.split('\\').pop();
  const targetBase = filename.split('/').pop()?.split('\\').pop();

  return loadedBase === targetBase;
};

// --- Print-in-flight state ----------------------------------------------
const isLoading = ref<boolean>(false);

const progressFraction = computed(() =>
    progress.value && typeof progress.value.fraction === "number"
        ? progress.value.fraction
        : 0,
);
const progressPercent = computed(() => progressFraction.value.toFixed(1));

// --- Time-estimate state -------------------------------------------------
//
// ``startedAt`` captures ``Date.now()`` the moment the interpreter
// enters ``RUNNING``. It survives pause / resume (real elapsed time
// is what we want to extrapolate from, not time spent moving) and is
// cleared only when the program leaves both the running/paused and
// the loaded surfaces — i.e. on unload, fresh load, or terminal
// non-active states. The progress percentage is
// ``progressFraction / 100``; extrapolating total wall-clock time is
// ``elapsed / fraction``, with the remaining slice = ``total - elapsed``.
const startedAt = ref<number | null>(null);

watch(isRunning, (running, wasRunning) => {
  if (running && !wasRunning) {
    // Fresh start OR resume from pause — restart the timer so
    // the percentage matches the wall-clock-elapsed denominator.
    startedAt.value = Date.now();
  }
  // ``running === false``: leave the value alone. The user can read
  // the frozen ETA while paused; clearing it would make the row flash
  // between "Est. remaining: …" and "Estimating…" on every pause.
});

watch([isActive, isLoaded], ([active, loaded]) => {
  if (!active && !loaded) {
    startedAt.value = null;
  }
});

const remainingMs = computed<number | null>(() => {
  if (!isRunning.value) return null;
  if (startedAt.value === null) return null;
  const fraction = progressFraction.value / 100;
  if (!Number.isFinite(fraction) || fraction <= 0 || fraction >= 1) return null;
  const elapsed = Date.now() - startedAt.value;
  if (!Number.isFinite(elapsed) || elapsed <= 0) return null;
  const total = elapsed / fraction;
  return Math.max(0, total - elapsed);
});

const formatRemaining = (ms: number): string => {
  const totalSec = Math.round(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
};

// ``remainingMs`` reads ``Date.now()``, which Vue does NOT track as
// a reactive dependency. The interval below re-evaluates the
// computed once per second while the program is running so the
// "Est. remaining" row ticks down without a watcher on every clock
// tick elsewhere in the app.
let remainingTimerId: ReturnType<typeof setInterval> | null = null;

// Cap the recent-files list to the five newest G-code / NGC entries.
const PRINTABLE_EXTENSIONS = [".gcode", ".ngc"];

const printableFiles = computed<ProgramFile[]>(() => {
  if (!Array.isArray(files.value)) return [];
  return files.value
      .filter((entry) => {
        if (!entry || typeof entry.name !== "string") return false;
        const lowered = entry.name.toLowerCase();
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

async function loadFile(filename: string) {
  if (!filename) return;

  if (isLoading.value) return;

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
    // Call ``progressFacade`` directly. The state facade's
    // ``useMachineStore`` is state-only — it has no
    // ``loadProgram`` action, so going through ``store.xxxProgram``
    // would throw ``is not a function`` and the HTTP request
    // would never fire. Failures are routed through
    // ``reportCommandFailure`` so the console row + toast match
    // every other manual trigger.
    const result = await progressFacade.loadProgram(filename);
    if (result.ok) {
      await fetchFiles();
    } else {
      reportCommandFailure(`load ${filename}`, result);
    }
  } finally {
    isLoading.value = false;
  }
}

async function startLoadedProgram() {
  if (systemState.value !== SystemState.LOADED) {
    consoleStore.error(`[ActivePrintWidget] Ignored start: Machine is ${systemState.value}, not Loaded.`);
    return;
  }
  consoleStore.debug("[ActivePrintWidget] Requesting start...");
  const result = await progressFacade.runProgram();
  if (result.failed) reportCommandFailure("start program", result);
}

async function unloadProgram() {
  consoleStore.debug("[ActivePrintWidget] Unloading program...");
  const result = await progressFacade.unloadProgram();
  if (result.failed) reportCommandFailure("unload program", result);
}

async function pausePrint() {
  if (systemState.value !== SystemState.RUNNING) {
    consoleStore.error("[ActivePrintWidget] Ignored pause request: Machine is not running.");
    return;
  }

  consoleStore.debug("[ActivePrintWidget] Requesting pause...");
  const result = await progressFacade.pauseProgram();
  if (result.failed) reportCommandFailure("pause program", result);
}

async function resumePrint() {
  if (systemState.value !== SystemState.PAUSED) {
    consoleStore.error("[ActivePrintWidget] Ignored resume request: Machine is not paused.");
    return;
  }

  consoleStore.debug("[ActivePrintWidget] Requesting resume...");
  const result = await progressFacade.resumeProgram();
  if (result.failed) reportCommandFailure("resume program", result);
}

async function stopPrint() {
  if (systemState.value !== SystemState.RUNNING && systemState.value !== SystemState.PAUSED) {
    consoleStore.error("[ActivePrintWidget] Ignored stop request: No active program to stop.");
    return;
  }

  consoleStore.debug("[ActivePrintWidget] Requesting abort/stop...");
  const result = await progressFacade.stopProgram();
  if (result.failed) reportCommandFailure("stop program", result);
}
</script>

<template>
  <BaseCard title=" 📂 Programs">
    <!-- Top-bar: Start button. (Hidden while active) -->

    <template #header-actions>
      <div v-if="!isActive" class="w-48" >
        <BaseButton
            variant="success"

            class="w-full"
            :disabled="!isLoaded"
            @click="startLoadedProgram"
        >Start
        </BaseButton>
      </div>
    </template>
    <template #footer-actions>

    </template>


    <!-- File list (Hidden while active) -->
    <div v-if="!isActive" class="p-4 border-b border-gray-700">



      <ul v-if="printableFiles.length > 0" class="divide-y divide-gray-700/60">
        <li
            v-for="file in printableFiles"
            :key="file.name"
            class="flex items-center justify-between py-2 gap-3 rounded px-2"
            :class="isLoadedFile(file.name) ? 'bg-blue-900/40 ring-1 ring-blue-500/40' : ''"
        >
          <span
              class="text-sm font-mono truncate"
              :class="isLoadedFile(file.name) ? 'text-blue-300 font-semibold' : 'text-gray-200'"
              :title="file.name"
          >
            {{ file.name }}
          </span>
          <BaseButton
              :variant="isLoadedFile(file.name) ? 'danger' : 'primary'"
              size="sm"
              class="shrink-0"
              :loading="isLoading && !isLoadedFile(file.name)"
              :disabled="isLoading || (systemState === SystemState.RUNNING || systemState === SystemState.PAUSED)"
              @click="isLoadedFile(file.name) ? unloadProgram() : loadFile(file.name)"
          >
            <span v-if="isLoadedFile(file.name)">Unload</span>
            <span v-else>Load</span>
          </BaseButton>
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

    <!-- Standby hint -->
    <div
        v-if="!isActive && !isLoaded"
        class="p-4 flex flex-col space-y-2"
    >
      <p class="text-xs text-gray-500 text-center">
        Load a program to start a job.
      </p>
    </div>

    <!-- Loaded hint -->
    <div
        v-else-if="isLoaded"
        class="p-4 flex flex-col space-y-2"
    >
      <p class="text-xs text-gray-500 text-center">
        Press <span class="font-semibold text-blue-300">Start</span> above
        to begin the run.
      </p>
    </div>

    <!-- Active view -->
    <div v-else class="p-4 flex flex-col space-y-4">
      <div class="flex items-center">
        <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
          <span class="mr-2">🖨️</span>
          {{ isPaused ? "Paused" : "Printing" }}
        </h2>
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
          <span>Line {{ progress.currentLine }}</span>
          <span>of {{ progress.totalLines || "?" }}</span>
        </div>
        <div
            v-if="remainingMs !== null"
            class="flex items-center justify-between text-[10px] text-gray-400 font-mono"
            data-testid="active-print-remaining"
        >
          <span>Est. remaining</span>
          <span>{{ formatRemaining(remainingMs) }}</span>
        </div>
        <div
            v-else-if="isRunning"
            class="text-[10px] text-gray-500 font-mono italic"
        >
          Estimating…
        </div>
      </div>

      <div class="flex items-center gap-2 pt-2">
        <BaseButton
            class="flex-1"
            :variant="isPaused ? 'success' : 'primary'"
            @click="isPaused ? resumePrint() : pausePrint()"
        >
          {{ isPaused ? "Resume" : "Pause" }}
        </BaseButton>
        <BaseButton
            variant="danger"
            class="flex-1"
            @click="stopPrint"
        >
          Stop / Cancel
        </BaseButton>
      </div>

      <span v-if="!isRunning && !isPaused" class="text-xs text-gray-500 italic">
        Program loaded but not yet running.
      </span>
    </div>
  </BaseCard>
</template>