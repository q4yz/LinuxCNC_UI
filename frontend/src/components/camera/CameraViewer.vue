<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from "vue";
import type { Ref, ComputedRef } from "vue";
import { storeToRefs } from "pinia";

import { useCameraStore, defaultPreferenceForActive } from "../../stores/cameraStore";
import type { CameraDevice, CameraPreference } from "../../stores/cameraTypes";
import BaseButton from "../../ui/BaseButton.vue";
import BaseCard from "../../ui/BaseCard.vue";

// Simple logger for the camera module. Uses console.debug so it
// doesn't spam the production console.
const logger = {
  debug: (...args: unknown[]): void => {
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

const activeDevice: ComputedRef<CameraDevice | null> = computed(() => {
  return devices.value.find((device) => device.id === activeCameraId.value) ?? null;
});

const activePreference: ComputedRef<CameraPreference> = computed<CameraPreference>(() => {
  const stored = cameraPreferences.value[activeCameraId.value];
  return stored ?? defaultPreferenceForActive();
});

const cameraName: ComputedRef<string> = computed(() => {
  const customName = activePreference.value.customName.trim();
  return customName || activeDevice.value?.name || activeCameraId.value;
});

// CSS ``transform`` string for the live feed. Composes the
// operator-configured quarter-turn rotation with the optional
// horizontal mirror. Both apply independently — rotating then
// mirroring is the same as mirroring then rotating for an
// orthogonal axis swap, but the order is fixed here so the inline
// style stays readable in the rendered DOM. ``rotate === 0`` and
// ``!mirror`` short-circuit to the literal ``none`` so the element
// gets no transform attribute when no orientation is set.
const cameraTransform: ComputedRef<string> = computed(() => {
  const { rotate, mirror } = activePreference.value;
  if (!rotate && !mirror) return "none";
  const parts: string[] = [];
  if (rotate) parts.push(`rotate(${rotate}deg)`);
  if (mirror) parts.push("scaleX(-1)");
  return parts.join(" ");
});

// ─────────────────────────────────────────────────────────────────
// Stream lifecycle
// ─────────────────────────────────────────────────────────────────
//
// On plain HTTP the browser caps the page at 6 concurrent HTTP/1.1
// connections per origin. The MJPEG ``<img>`` holds one slot for its
// whole lifetime, the telemetry WebSocket another — so the switch
// sequence below is written to **release the old stream first and
// wait out a grace period before opening the next one**, giving the
// browser time to reclaim the old slot instead of queueing the new
// stream (and every 1 Hz poll behind it) into a full pool — the
// "all pending" freeze.
//
// Small single-purpose methods keep that ordering explicit:
//
//   releaseStream()            → drop the <img> (cancel socket)
//   scheduleStreamOpen(delay)  → grace timer, then openStream()
//   openStream()               → set the cache-busted <img> src
//   handleStreamError()        → backoff bookkeeping + diagnostic probe

const MAX_RETRY_DELAY_MS = 15_000;
const STREAM_RETRY_BASE_MS = 2_000;
const STREAM_CONNECT_DELAY_MS = 1_200;

const streamUrl: Ref<string> = ref("");
let streamTimer: ReturnType<typeof setTimeout> | null = null;
let retryCount = 0;

/** Drop the current ``<img>`` — the browser cancels the socket. */
function releaseStream(): void {
  if (streamTimer) {
    clearTimeout(streamTimer);
    streamTimer = null;
  }
  streamUrl.value = "";
}

/** Build the same-origin stream URL with a cache-buster. */
function streamUrlFor(cameraId: string): string {
  return `/api/v1/modules/camera/stream?id=${encodeURIComponent(cameraId)}&t=${Date.now()}`;
}

/** Mount the new ``<img>`` (assumes ``releaseStream`` already ran). */
function openStream(): void {
  const cameraId = activeCameraId.value;
  if (!cameraId) return;
  streamUrl.value = streamUrlFor(cameraId);
}

/** Grace delay, then open — never opens while a timer is pending. */
function scheduleStreamOpen(delayMs: number = STREAM_CONNECT_DELAY_MS): void {
  if (streamTimer) clearTimeout(streamTimer);
  if (!activeCameraId.value) return;
  streamTimer = setTimeout(openStream, delayMs);
}

/**
 * Exponential backoff on stream failure. The backend enforces a
 * 5-second cooldown after a failed open/read; the frontend mirrors
 * that with a capped exponential backoff so we don't hammer the
 * server while the hardware is locked. The diagnostic probe explains
 * WHY the stream is down (unreachable / login page / credentials
 * rejected / dependency missing) so the operator sees the same
 * actionable text the backend logged, not a generic broken-image
 * hint from /status.
 */
function handleStreamError(): void {
  retryCount += 1;
  const delay = Math.min(
    STREAM_RETRY_BASE_MS * Math.pow(2, retryCount - 1),
    MAX_RETRY_DELAY_MS,
  );
  logger.debug(
    `Camera stream failed (attempt ${retryCount}); retrying in ${delay}ms`,
  );
  releaseStream();
  scheduleStreamOpen(delay);
  // Ask the backend for the upstream verdict. Falls back to
  // ``refreshStreamMessage()`` internally when no id is set or the
  // probe reports healthy — the supervisor status row still carries
  // USB dependency messages.
  void store.probeStreamFailure();
}

/** Reset the backoff counter when the stream succeeds. */
function handleStreamLoad(): void {
  retryCount = 0;
}

// Re-run the release → delay → open sequence anytime the active
// camera changes.
watch(activeCameraId, () => {
  retryCount = 0;
  releaseStream();
  scheduleStreamOpen();
});

// If the operator hides the active camera from the Settings panel
// while the viewer is mounted, step forward to the next visible one.
// ``cycleCamera`` already filters out hidden cameras, so the watcher
// below lands on a non-hidden row automatically — or clears the
// active id when every camera is hidden.
watch(
  () => [
    activeCameraId.value,
    cameraPreferences.value[activeCameraId.value]?.hidden,
  ],
  ([id, hidden]) => {
    if (id && hidden === true) {
      store.cycleCamera();
    }
  },
);

onMounted(() => {
  store.fetchDevices();
  store.refreshStreamMessage();
  scheduleStreamOpen();
});

// Clean up when leaving the page to free the USB hardware and
// await any in-flight preference write so the most recent
// keystroke is not lost on navigation.
onBeforeUnmount(async () => {
  releaseStream();
  await store.awaitInFlightPreferenceWrite();
});
</script>

<template>
  <BaseCard
    class="relative flex min-h-[300px] w-full items-center justify-center bg-gray-950"
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
      <BaseButton
        v-if="!isLoading"
        variant="secondary"
        size="sm"
        class="mt-4"
        @click="streamMessage ? store.refreshStreamMessage() : store.fetchDevices()"
      >
        {{ streamMessage ? "Re-check" : "Refresh Cameras" }}
      </BaseButton>
    </div>

    <div
      v-if="activeCameraId"
      class="pointer-events-none absolute left-4 top-4 max-w-[80%] truncate rounded border border-gray-700 bg-gray-900/80 px-3 py-1.5 font-mono text-xs text-gray-200 backdrop-blur"
    >
      {{ cameraName }}
    </div>

    <BaseButton
      v-if="activeCameraId"
      variant="primary"
      :disabled="devices.length < 2"
      class="absolute bottom-4 right-4"
      aria-label="Switch Camera"
      title="Switch Camera"
      @click="store.cycleCamera()"
    >
      Switch Camera
    </BaseButton>
  </BaseCard>
</template>