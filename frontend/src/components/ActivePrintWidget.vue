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
import {useLoadedProgram} from "../composables/useLoadedProgram";
import {progressFacade} from "../facades/progressFacade";
import {reportCommandFailure, describeErrorOr} from "../core/error-format";
import {FileEntry} from "../entities/files";
import {BaseButton, Icon} from "../ui/index.ts";
import BaseCard from "../ui/BaseCard.vue";
import PrintObjects from "./print/PrintObjects.vue";
import {usePrintTuning} from "../composables/usePrintTuning";
import {useFileThumbnails} from "../composables/useFileThumbnails";


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
// deep ``UnwrapRef`` would strip the ``FileEntry`` class privates.
const files = shallowRef<FileEntry[]>([]);
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

// --- Loaded-file lookup (shared with the G-code file list) -------------
// Files are addressed by their path under nc_files/ (programs may live
// in project folders), so "loaded" is matched by path, not base name.
const { loadedPathAmong, loadedRelativePath } = useLoadedProgram();
const loadedPath = computed(() => loadedPathAmong(files.value.filter((f) => f.isFile).map((f) => f.path)));
const isLoadedFile = (path: string): boolean => loadedPath.value === path;

// --- Print-in-flight state ----------------------------------------------
const isLoading = ref<boolean>(false);

// The loaded / running program's slicer thumbnail (generic icon without one).
const { thumbnails, ensure: ensureThumbnail } = useFileThumbnails();
watch(loadedRelativePath, (path) => {
  if (path) void ensureThumbnail(path);
}, { immediate: true });
const programThumbnail = computed(() =>
    loadedRelativePath.value ? thumbnails.value[loadedRelativePath.value]?.dataUrl ?? null : null);

// The header says what the machine does with the program.
const cardTitle = computed(() => (isPaused.value ? "Paused" : isRunning.value ? "Printing" : "Programs"));

// The slicer's own progress (M73), when the file has it: then it is the only
// one shown — percent, bar and time left — instead of the line count and
// the estimate from the elapsed time.
const { state: tuning } = usePrintTuning();
const slicerPercent = computed<number | null>(() => tuning.value?.progress?.percent ?? null);
const slicerRemainingMin = computed<number | null>(() => tuning.value?.progress?.remaining_min ?? null);
const hasSlicerProgress = computed(() => slicerPercent.value !== null || slicerRemainingMin.value !== null);

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

/** The bar's fill (%): the slicer's percent when it has one, else the line count's. */
const barPercent = computed(() => slicerPercent.value ?? progressFraction.value);

/** One line under the program name: the slicer's "45 % · 1h 2m left" when
 *  the file has M73, else "12.3 % · line 120 / 3400 · 5m 20s left". */
const progressLine = computed(() => {
  const parts: string[] = [];
  if (hasSlicerProgress.value) {
    if (slicerPercent.value !== null) parts.push(`${slicerPercent.value.toFixed(0)} %`);
    if (slicerRemainingMin.value !== null) parts.push(`${formatRemaining(slicerRemainingMin.value * 60_000)} left`);
    return parts.join(" · ");
  }
  if (progressFraction.value > 0) parts.push(`${progressPercent.value} %`);
  parts.push(`line ${progress.value.currentLine} / ${progress.value.totalLines || "?"}`);
  if (remainingMs.value !== null) parts.push(`${formatRemaining(remainingMs.value)} left`);
  else if (isRunning.value) parts.push("estimating…");
  return parts.join(" · ");
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

const printableFiles = computed<FileEntry[]>(() => {
  if (!Array.isArray(files.value)) return [];
  return files.value
      .filter((entry) => {
        if (!entry || !entry.isFile || typeof entry.name !== "string") return false;
        const lowered = entry.name.toLowerCase();
        return PRINTABLE_EXTENSIONS.some((ext) => lowered.endsWith(ext));
      })
      .slice()
      .sort((a, b) => {
        const aTime = a.modifiedMs;
        const bTime = b.modifiedMs;
        return bTime - aTime;
      })
      .slice(0, 3);
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
  if (result.failed) {
    reportCommandFailure("resume program", result);
  } else {
    // resumeProgram() always reverses Pause & Inspect on the backend
    // (a safe no-op if it was never engaged) — mirror that here so a
    // stale "Inspecting" badge never survives a resume.
    isInspecting.value = false;
  }
}

// --- Pause & Inspect -------------------------------------------------
//
// Only ever valid on top of an already-paused program — LinuxCNC's
// eoffset lift only applies cleanly while paused (see
// `.agent/component/pause_inspect.md`). The backend has no status
// feed for "is inspect currently engaged" (just write-only HAL
// pins), so `isInspecting` is purely local UI state: set on a
// successful `pauseInspect` call, cleared on resume or on leaving
// Paused by any other path (stop/estop/etc).
const isInspecting = ref<boolean>(false);

watch(isPaused, (paused) => {
  if (!paused) isInspecting.value = false;
});

async function pauseInspectAction() {
  if (systemState.value !== SystemState.PAUSED) {
    consoleStore.error("[ActivePrintWidget] Ignored pause & inspect request: Machine is not paused.");
    return;
  }

  consoleStore.debug("[ActivePrintWidget] Requesting pause & inspect...");
  const result = await progressFacade.pauseInspect();
  if (result.failed) {
    reportCommandFailure("pause & inspect", result);
  } else {
    isInspecting.value = true;
  }
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
  <BaseCard :title="cardTitle" :icon="isActive ? 'running' : 'folder'">
    <template #header-actions>
      <BaseButton
          v-if="!isActive"
          variant="success"
          class="w-32"
          :disabled="!isLoaded"
          @click="startLoadedProgram"
      >Start</BaseButton>
    </template>

    <!-- The loaded / running program: its slicer thumbnail and name -->
    <div v-if="isLoaded || isActive" class="flex items-center gap-3 px-4 pt-3" data-testid="active-print-program">
      <img
          v-if="programThumbnail"
          :src="programThumbnail"
          :alt="`Preview of ${loadedRelativePath}`"
          class="h-14 w-20 shrink-0 rounded border border-gray-600 bg-gray-900 object-contain"
          data-testid="active-print-thumbnail"
      />
      <span
          v-else
          class="flex h-14 w-20 shrink-0 items-center justify-center rounded border border-gray-600 bg-gray-900"
          title="No embedded thumbnail"
          data-testid="active-print-thumbnail"
      ><Icon name="file" size="h-7 w-7" class="text-gray-500" /></span>
      <div class="min-w-0 flex-1">
        <div class="truncate font-mono text-sm text-gray-200" :title="status.file">
          {{ loadedRelativePath || status.file || "(unknown file)" }}
        </div>
        <div v-if="isLoaded" class="text-xs text-gray-500">Loaded — press <span class="font-semibold text-green-400">Start</span>.</div>
        <div v-else class="font-mono text-xs text-gray-400" data-testid="active-print-progress-line">{{ progressLine }}</div>
      </div>
    </div>

    <!-- File list (not while a program runs) -->
    <div v-if="!isActive" class="px-2 py-2">
      <ul v-if="printableFiles.length > 0" class="divide-y divide-gray-700/60">
        <li
            v-for="file in printableFiles"
            :key="file.path"
            class="flex items-center justify-between gap-3 rounded px-2 py-1.5"
            :class="isLoadedFile(file.path) ? 'bg-blue-900/40 ring-1 ring-blue-500/40' : ''"
        >
          <span
              class="truncate font-mono text-sm"
              :class="isLoadedFile(file.path) ? 'font-semibold text-blue-300' : 'text-gray-200'"
              :title="file.path"
          >{{ file.path }}</span>
          <BaseButton
              :variant="isLoadedFile(file.path) ? 'danger' : 'primary'"
              size="sm"
              class="shrink-0"
              :loading="isLoading && !isLoadedFile(file.path)"
              :disabled="isLoading"
              @click="isLoadedFile(file.path) ? unloadProgram() : loadFile(file.path)"
          >{{ isLoadedFile(file.path) ? "Unload" : "Load" }}</BaseButton>
        </li>
      </ul>
      <div v-else-if="isLoadingList" class="px-2 text-xs italic text-gray-500">Loading program list…</div>
      <div v-else-if="loadError" class="px-2 text-xs italic text-red-400">Failed to load program list: {{ loadError }}</div>
      <div v-else class="px-2 text-xs italic text-gray-500">No printable G-code files found. Upload one from the Files view.</div>
    </div>

    <!-- Running / paused -->
    <div v-else class="space-y-3 p-4 pt-3">
      <div class="h-2 w-full overflow-hidden rounded border border-gray-700 bg-gray-900" data-testid="active-print-bar">
        <div
            class="h-full transition-all duration-300"
            :class="isPaused ? 'bg-yellow-500' : 'bg-blue-500'"
            :style="{ width: `${barPercent}%` }"
        ></div>
      </div>

      <div class="flex items-center gap-2">
        <BaseButton
            class="flex-1"
            :variant="isPaused ? 'success' : 'primary'"
            @click="isPaused ? resumePrint() : pausePrint()"
        >{{ isPaused ? "Resume" : "Pause" }}</BaseButton>
        <BaseButton
            v-if="isPaused && !isInspecting"
            class="flex-1"
            variant="secondary"
            title="Lift the tool clear of the work and inhibit the spindle"
            data-testid="pause-inspect-button"
            @click="pauseInspectAction"
        >Inspect</BaseButton>
        <BaseButton variant="danger" class="flex-1" @click="stopPrint">Stop / Cancel</BaseButton>
      </div>
      <div
          v-if="isPaused && isInspecting"
          class="rounded border border-yellow-700 bg-yellow-900/30 px-2 py-1.5 text-center text-xs text-yellow-300"
          role="status"
          data-testid="pause-inspect-active"
      >Inspecting — tool lifted, spindle inhibited</div>

      <!-- Exclude objects of the running print -->
      <PrintObjects />
    </div>
  </BaseCard>
</template>
