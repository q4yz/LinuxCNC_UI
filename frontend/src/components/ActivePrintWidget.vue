<script setup>
// ActivePrintWidget — a compact dashboard panel that mirrors the active
// LinuxCNC program run. It deliberately keeps two visual states:
//
//   1. Standby (not printing) — surfaces the five newest G-code files so
//      the operator can pick one to run from the dashboard instead of
//      having to drill into the dedicated Files view first.
//   2. Active (printing / paused) — shows the loaded filename, a
//      progress bar bound to ``printProgress``, and the Pause/Resume and
//      Stop controls. The widget never mutates local state directly:
//      every action delegates to the Pinia machine store, which in
//      turn issues the appropriate HTTP call. The backend's telemetry
//      stream then updates ``status.interp_state`` / ``task_state`` on
//      the next polling cycle and the UI re-renders.

import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useMachineStore } from "../stores/machine-compat";
import { NcFilesService } from "../../generated/api/services/NcFilesService";

const store = useMachineStore();
const { status, isPrinting, isPaused, printProgress } = storeToRefs(store);

// Local UI state — the file list is reloaded on mount and whenever the
// operator returns from the Files page; the count is intentionally
// bounded to 5 per the dashboard design.
const recentFiles = ref([]);
const isLoadingFiles = ref(false);
const loadError = ref("");

// Only G-code / NGC files are interesting from a printing standpoint.
// ``NcFilesService.listFiles`` returns the full directory listing
// (including any non-program artefacts), so the widget filters locally.
const PRINTABLE_EXTENSIONS = [".gcode", ".ngc"];

function isPrintableFile(entry) {
  if (!entry || typeof entry.filename !== "string") return false;
  const lowered = entry.filename.toLowerCase();
  return PRINTABLE_EXTENSIONS.some((ext) => lowered.endsWith(ext));
}

const printableFiles = computed(() => {
  if (!Array.isArray(recentFiles.value)) return [];
  return recentFiles.value
    .filter(isPrintableFile)
    // Newest first — ``modified`` is the ISO-8601 string the backend
    // already ships; ``Date.parse`` handles ISO-8601 natively.
    .slice()
    .sort((a, b) => {
      const aTime = Date.parse(a.modified || "") || 0;
      const bTime = Date.parse(b.modified || "") || 0;
      return bTime - aTime;
    })
    .slice(0, 5);
});

async function loadRecentFiles() {
  isLoadingFiles.value = true;
  loadError.value = "";
  try {
    const list = await NcFilesService.listFiles();
    recentFiles.value = Array.isArray(list) ? list : [];
  } catch (err) {
    loadError.value = err && err.message ? err.message : "Unknown error";
    recentFiles.value = [];
  } finally {
    isLoadingFiles.value = false;
  }
}

function printFile(filename) {
  if (!filename) return;
  // The store action handles loading + running; the backend's
  // telemetry stream will flip ``isPrinting`` once LinuxCNC reports
  // the task as executing.
  void store.startProgram(filename);
}

function togglePause() {
  if (isPaused.value) {
    void store.resumeProgram();
  } else {
    void store.pauseProgram();
  }
}

function stopPrint() {
  void store.abortProgram();
}

// Pretty-print the progress as an integer percentage to avoid the bar
// "dancing" between values like 33.3333% and 33.3334%.
const progressPercent = computed(() => printProgress.value.toFixed(1));

onMounted(() => {
  void loadRecentFiles();
});
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl flex flex-col">
    <!-- Standby view: no program is loaded or the interpreter is idle. -->
    <div
      v-if="!isPrinting && !isPaused"
      class="p-4 flex flex-col space-y-4"
    >
      <div class="flex items-center justify-between">
        <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
          <span class="mr-2">💤</span> Standby
        </h2>
        <button
          type="button"
          class="text-xs text-blue-400 hover:text-blue-300"
          :disabled="isLoadingFiles"
          @click="loadRecentFiles"
        >
          {{ isLoadingFiles ? "Refreshing..." : "Refresh" }}
        </button>
      </div>

      <p class="text-xs text-gray-500">
        No active print. Pick one of the recent files to start a job.
      </p>

      <div v-if="loadError" class="text-xs text-red-400">
        Failed to load files: {{ loadError }}
      </div>

      <ul v-else-if="printableFiles.length > 0" class="divide-y divide-gray-700/60">
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

      <div
        v-else-if="!isLoadingFiles"
        class="text-xs text-gray-500 italic"
      >
        No printable G-code files found. Upload one from the Files view.
      </div>
    </div>

    <!-- Active view: a program is loaded. The same panel renders for
         both the running and paused states; only the button label and
         progress-bar hue change so the layout does not jump. -->
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
          @click="togglePause"
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
    </div>
  </div>
</template>