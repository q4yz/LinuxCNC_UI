<script setup>
import { computed, onMounted } from "vue";
import { storeToRefs } from "pinia";

import { useCameraStore } from "../cameraStore.js";

const store = useCameraStore();
const { devices, activeCameraId, cameraPreferences, isLoading, error } =
  storeToRefs(store);

const activeDevice = computed(() => {
  return devices.value.find((device) => device.id === activeCameraId.value) ?? null;
});

const activePreference = computed(() => {
  return (
    cameraPreferences.value[activeCameraId.value] ?? {
      flip: false,
      mirror: false,
      customName: "",
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

const streamUrl = computed(() => {
  if (!activeCameraId.value) return "";
  return `/api/v1/modules/camera/stream?id=${encodeURIComponent(activeCameraId.value)}`;
});

onMounted(() => {
  store.fetchDevices();
});
</script>

<template>
  <section
    class="relative flex min-h-[300px] w-full items-center justify-center overflow-hidden rounded-lg border border-gray-700 bg-gray-950 shadow-xl"
    aria-label="Camera viewer"
  >
    <img
      v-if="activeCameraId"
      :key="activeCameraId"
      :src="streamUrl"
      :alt="`Live feed from ${cameraName}`"
      :style="{ transform: cameraTransform }"
      class="h-full min-h-[300px] w-full object-contain transition-transform duration-200"
    >

    <div
      v-else
      class="flex min-h-[300px] flex-col items-center justify-center px-6 text-center"
    >
      <svg
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
      <p class="text-sm font-semibold text-gray-300">
        {{ isLoading ? "Discovering cameras..." : "No camera available" }}
      </p>
      <p v-if="error" class="mt-2 max-w-md text-xs text-red-300">
        {{ error }}
      </p>
      <button
        v-if="!isLoading"
        type="button"
        class="mt-4 rounded bg-gray-700 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-gray-600"
        @click="store.fetchDevices()"
      >
        Refresh Cameras
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
