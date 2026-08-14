<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from "vue";
import { storeToRefs } from "pinia";

import { useCameraStore } from "../cameraStore.js";

// Simple logger for the camera module. Uses console.debug so it
// doesn't spam the production console.
const logger = {
  debug: (...args) => {
    if (import.meta.env.DEV) console.debug("[CameraViewer]", ...args);
  },
};

const store = useCameraStore();
const {
  devices,
  activeCameraId,
  cameraPreferences,
  isLoading,
  error,
  streamMessage,
} = storeToRefs(store);

const activeDevice = computed(() => {
  return devices.value.find((device) => device.id === activeCameraId.value) ?? null;
});

const activePreference = computed(() => {
  return (
    cameraPreferences.value[activeCameraId.value] ?? {
      flip: false,
      mirror: false,
      customName: "",
      hidden: false,
    }
  );
});

const cameraName = computed(() => {
  const customName = activePreference.value.customName.trim();
  return customName || activeDevice.value?.name || activeCameraId.value;
});

const cameraTransform = computed(() => {
  const { flip, mirror } = activePreference.value;
  if (flip && mirror) return "scale(-1, -1)";
  if (mirror) return "scaleX(-1)";
  if (flip) return "scaleY(-1)";
  return "none";
});

// --- Hardware Race Condition Fix ---
const streamUrl = ref("");
let streamTimer = null;
let retryCount = 0;
const MAX_RETRY_DELAY_MS = 5000;

const startStream = () => {
  if (streamTimer) clearTimeout(streamTimer);

  if (!activeCameraId.value) {
    streamUrl.value = "";
    return;
  }

  // Add a 300ms delay so the backend can release the old lock
  streamTimer = setTimeout(() => {
    // Append Date.now() to bypass aggressive browser caching
    streamUrl.value = `/api/v1/modules/camera/stream?id=${encodeURIComponent(activeCameraId.value)}&t=${Date.now()}`;
  }, 300);
};

// Exponential backoff on stream failure. The backend enforces a
// 5-second cooldown after a failed open/read; the frontend mirrors
// that with a capped exponential backoff so we don't hammer the
// server while the hardware is locked. Every retry also refreshes
// ``streamMessage`` so a dependency problem surfaces with a single
// operator-facing hint rather than the silent retry loop.
const handleStreamError = () => {
  retryCount += 1;
  const delay = Math.min(1000 * Math.pow(2, retryCount), MAX_RETRY_DELAY_MS);
  logger.debug(
    `Camera stream failed (attempt ${retryCount}); retrying in ${delay}ms`
  );
  streamUrl.value = "";
  if (streamTimer) clearTimeout(streamTimer);
  streamTimer = setTimeout(() => {
    startStream();
  }, delay);
  // Pull the latest diagnostic from the supervisor. The operator
  // sees a plain-English hint ("ustreamer is not installed…") instead
  // of an opaque broken <img>.
  store.refreshStreamMessage();
};

// Reset the backoff counter when the stream succeeds.
const handleStreamLoad = () => {
  retryCount = 0;
};

// Re-run the delay anytime the active camera changes
watch(activeCameraId, () => {
  retryCount = 0;
  streamUrl.value = ""; // Instantly destroy the old <img> tag to drop the socket
  startStream();
});

// If the operator hides the active camera from the Settings panel
// while the viewer is mounted, step forward to the next visible one.
// ``cycleCamera`` already filters out hidden cameras, so the watcher
// below lands on a non-hidden row automatically — or clears the
// active id when every camera is hidden.
watch(
  () => [activeCameraId.value, cameraPreferences.value[activeCameraId.value]?.hidden],
  ([id, hidden]) => {
    if (id && hidden === true) {
      store.cycleCamera();
    }
  },
);

onMounted(() => {
  store.fetchDevices();
  store.refreshStreamMessage();
  startStream();
});

// Clean up when leaving the page to free the USB hardware and
// await any in-flight preference write so the most recent
// keystroke is not lost on navigation.
onBeforeUnmount(async () => {
  if (streamTimer) clearTimeout(streamTimer);
  streamUrl.value = "";
  await store.awaitInFlightPreferenceWrite();
});
</script>

<template>
  <section
    class="relative flex min-h-[300px] w-full items-center justify-center overflow-hidden rounded-lg border border-gray-700 bg-gray-950 shadow-xl"
    aria-label="Camera viewer"
  >
    <!-- 1. The active stream -->
    <img
      v-if="streamUrl"
      :key="streamUrl"
      :src="streamUrl"
      :alt="`Live feed from ${cameraName}`"
      :style="{ transform: cameraTransform }"
      class="h-full min-h-[300px] w-full object-contain transition-transform duration-200"
      @error="handleStreamError"
      @load="handleStreamLoad"
    >

    <!-- 2. The 300ms "breath" loading state -->
    <div
      v-else-if="activeCameraId"
      class="flex min-h-[300px] w-full flex-col items-center justify-center text-center text-gray-400"
    >
      <div class="mb-3 h-8 w-8 animate-spin rounded-full border-2 border-blue-500 border-t-transparent"></div>
      <span class="text-sm font-semibold">Connecting to camera...</span>
    </div>

    <!-- 3. No camera selected / error state -->
    <div
      v-else
      class="flex min-h-[300px] flex-col items-center justify-center px-6 text-center"
    >
      <svg
        v-if="!streamMessage"
        class="mb-3 h-12 w-12 text-gray-600"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        aria-hidden="true"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="2"
          d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
        />
      </svg>
      <svg
        v-else
        class="mb-3 h-12 w-12 text-amber-400"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        aria-hidden="true"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="2"
          d="M12 9v2m0 4h.01M5.07 19h13.86c1.54 0 2.5-1.67 1.73-3L13.73 4a2 2 0 00-3.46 0L3.34 16c-.77 1.33.19 3 1.73 3z"
        />
      </svg>
      <p
        v-if="streamMessage"
        class="text-sm font-semibold text-amber-300"
        role="alert"
      >
        Camera unavailable
      </p>
      <p v-else class="text-sm font-semibold text-gray-300">
        {{ isLoading ? "Discovering cameras..." : "No camera available" }}
      </p>
      <p
        v-if="streamMessage"
        class="mt-2 max-w-md text-xs text-gray-300"
        role="status"
      >
        {{ streamMessage }}
      </p>
      <p v-else-if="error" class="mt-2 max-w-md text-xs text-red-300">
        {{ error }}
      </p>
      <button
        v-if="!isLoading"
        type="button"
        class="mt-4 rounded bg-gray-700 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-gray-600"
        @click="streamMessage ? store.refreshStreamMessage() : store.fetchDevices()"
      >
        {{ streamMessage ? "Re-check" : "Refresh Cameras" }}
      </button>
    </div>

    <div
      v-if="activeCameraId"
      class="pointer-events-none absolute left-4 top-4 max-w-[80%] truncate rounded border border-gray-700 bg-gray-900/80 px-3 py-1.5 font-mono text-xs text-gray-200 shadow backdrop-blur"
    >
      {{ cameraName }}
    </div>

    <button
      v-if="activeCameraId"
      type="button"
      :disabled="devices.length < 2"
      class="absolute bottom-4 right-4 rounded-full bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-lg transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-blue-900 disabled:text-gray-400"
      aria-label="Switch Camera"
      title="Switch Camera"
      @click="store.cycleCamera()"
    >
      Switch Camera
    </button>
  </section>
</template>