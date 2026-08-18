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

import {computed, ref, onMounted} from "vue";
import {storeToRefs} from "pinia";
import {useMachineStore, SystemState} from "../stores/stateFacade";
import {useBaseThreadStore} from "../stores/baseThread";
import {useConsoleStore} from "../stores/console";
import {progressFacade} from "../facades/progressFacade";
import {ProgramFile} from "../entities/progress";


const store = useMachineStore();
const baseThread = useBaseThreadStore();
const consoleStore = useConsoleStore();
const {systemState, status} = storeToRefs(store);
const {progress} = storeToRefs(baseThread);

// --- File list state -----------------------------------------------------
//
// `files` is the canonical list of programs on the active
// backend root. Refreshed on mount and after every successful load.
const files = ref<ProgramFile[]>([]);
const isLoadingList = ref<boolean>(false);
const loadError = ref<string | null>(null);

async function fetchFiles() {
  isLoadingList.value = true;
  loadError.value = null;
  try {
    const listing = await progressFacade.listProgramFiles();
    files.value = Array.isArray(listing) ? listing : [];
  } catch (err: any) {
    const detail = err?.body?.detail || err?.message || "unknown error";
    consoleStore.error(`[ActivePrintWidget] Failed to load file list: ${detail}`);
    loadError.value = detail;
    files.value = [];
  } finally {
    isLoadingList.value = false;
  }
}

onMounted(() => {
  fetchFiles();
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
    const result = await progressFacade.loadProgram(filename);
    if (result.ok) {
      consoleStore.success(`Loaded ${filename}. Press Start to begin.`);
      await fetchFiles();
    } else {
      consoleStore.error(
          `[ActivePrintWidget] Failed to load: ${result.failureReason}`,
          {popup: true, title: "Load failed"},
      );
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
  if (result.failed) {
    consoleStore.error(`[ActivePrintWidget] Failed to start: ${result.failureReason}`);
  }
}

async function unloadProgram() {
  consoleStore.debug("[ActivePrintWidget] Unloading program...");
  const result = await progressFacade.unloadProgram();
  if (result.failed) {
    consoleStore.error(`[ActivePrintWidget] Failed to unload: ${result.failureReason}`);
  }
}

async function pausePrint() {
  if (systemState.value !== SystemState.RUNNING) {
    consoleStore.error("[ActivePrintWidget] Ignored pause request: Machine is not running.");
    return;
  }

  consoleStore.debug("[ActivePrintWidget] Requesting pause...");
  const result = await progressFacade.pauseProgram();
  if (result.failed) {
    consoleStore.error(`[ActivePrintWidget] Failed to pause: ${result.failureReason}`);
  }
}

async function resumePrint() {
  if (systemState.value !== SystemState.PAUSED) {
    consoleStore.error("[ActivePrintWidget] Ignored resume request: Machine is not paused.");
    return;
  }

  consoleStore.debug("[ActivePrintWidget] Requesting resume...");
  const result = await progressFacade.resumeProgram();
  if (result.failed) {
    consoleStore.error(`[ActivePrintWidget] Failed to resume: ${result.failureReason}`);
  }
}

async function stopPrint() {
  if (systemState.value !== SystemState.RUNNING && systemState.value !== SystemState.PAUSED) {
    consoleStore.error("[ActivePrintWidget] Ignored stop request: No active program to stop.");
    return;
  }

  consoleStore.debug("[ActivePrintWidget] Requesting abort/stop...");
  const result = await progressFacade.stopProgram();
  if (result.failed) {
    consoleStore.error(`[ActivePrintWidget] Failed to stop print: ${result.failureReason}`);
  }
}
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl flex flex-col">
    <!-- Top-bar: Start button. -->
    <div class="p-4 border-b border-gray-700">
      <button
          type="button"
          :disabled="!isLoaded"
          @click="startLoadedProgram"
          class="w-full px-4 py-3 bg-green-600 hover:bg-green-500 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded font-semibold text-base transition-colors shadow"
      >Start
      </button>
    </div>

    <!-- File list -->
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
          <button
              type="button"
              :class="isLoadedFile(file.name)
              ? 'shrink-0 px-3 py-1 bg-red-600 hover:bg-red-500 text-white rounded text-xs font-semibold transition-colors'
              : 'shrink-0 px-3 py-1 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-900 disabled:cursor-wait text-white rounded text-xs font-semibold transition-colors'"
              :disabled="isLoading || (systemState === SystemState.RUNNING || systemState === SystemState.PAUSED)"
              @click="isLoadedFile(file.name) ? unloadProgram() : loadFile(file.name)"
          >
            <span v-if="isLoading && !isLoadedFile(file.name)">Loading…</span>
            <span v-else-if="isLoadedFile(file.name)">Unload</span>
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

      <span v-if="!isRunning && !isPaused" class="text-xs text-gray-500 italic">
        Program loaded but not yet running.
      </span>
    </div>
  </div>
</template>