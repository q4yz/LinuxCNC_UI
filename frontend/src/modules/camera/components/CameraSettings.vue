<script setup>
import { onMounted, ref } from "vue";
import { storeToRefs } from "pinia";

import { createModuleSettings } from "../../../core/modules/settings.js";
import { ModalButtonStyle, useConfirm } from "../../../core/confirm.js";
import { useCameraStore } from "../cameraStore.js";
import manifest from "../manifest.js";

const store = useCameraStore();
const {
  devices,
  cameraPreferences,
  isLoading: devicesLoading,
  error: devicesError,
  preferencesHydrated,
  streamMessage,
} = storeToRefs(store);
const settings = createModuleSettings(manifest.id);

const ipCameraUrl = ref("");
const settingsLoading = ref(false);
const settingsSaving = ref(false);
const settingsError = ref("");
const saveMessage = ref("");

function preferenceFor(id) {
  return (
    cameraPreferences.value[id] ?? {
      customName: "",
      flip: false,
      mirror: false,
      hidden: false,
    }
  );
}

function updateCustomName(id, event) {
  store.updatePreference(id, "customName", event.target.value);
}

function updateBooleanPreference(id, key, event) {
  store.updatePreference(id, key, event.target.checked);
}

async function loadBackendSettings() {
  settingsLoading.value = true;
  settingsError.value = "";

  try {
    const payload = await settings.readAll();
    ipCameraUrl.value =
      typeof payload.ip_camera_url === "string" ? payload.ip_camera_url : "";
  } catch (requestError) {
    settingsError.value =
      requestError instanceof Error
        ? requestError.message
        : "Unable to load camera settings";
  } finally {
    settingsLoading.value = false;
  }
}

async function saveIpCameraUrl() {
  settingsSaving.value = true;
  settingsError.value = "";
  saveMessage.value = "";

  try {
    const normalizedUrl = ipCameraUrl.value.trim();
    const payload = await settings.writeKey("ip_camera_url", normalizedUrl);
    ipCameraUrl.value =
      typeof payload.ip_camera_url === "string"
        ? payload.ip_camera_url
        : normalizedUrl;
    saveMessage.value = "IP camera URL saved.";
    await store.fetchDevices();
  } catch (requestError) {
    settingsError.value =
      requestError instanceof Error
        ? requestError.message
        : "Unable to save the IP camera URL";
  } finally {
    settingsSaving.value = false;
  }
}

/**
 * Confirm-and-delete an IP camera row. The store action clears the
 * ``ip_camera_url`` and drops the matching preference row in one
 * round-trip, so the persisted settings never orphan the removed
 * camera's custom name.
 *
 * @param {{ id: string, source: string }} device
 */
async function confirmRemove(device) {
  if (!device || device.source !== "ip") return;
  const shouldRemove = await useConfirm({
    title: "Remove IP camera?",
    question: `Remove "${device.id}" from this machine? The custom name and preferences for this camera will be deleted.`,
    confirmButtonText: "Remove",
    confirmButtonStyle: ModalButtonStyle.DANGER,
    rejectButtonText: "Cancel",
  });
  if (!shouldRemove) return;
  await store.deleteIpCamera(device);
}

onMounted(() => {
  store.fetchDevices();
  store.refreshStreamMessage();
  loadBackendSettings();
});
</script>

<template>
  <div class="space-y-8">
    <section class="space-y-3">
      <header>
        <h3 class="text-sm font-semibold uppercase tracking-wider text-gray-300">
          IP camera
        </h3>
        <p class="mt-1 text-xs text-gray-400">
          Add an HTTP or RTSP camera URL to the devices returned by the camera module.
        </p>
      </header>

      <form class="flex flex-col gap-3 sm:flex-row sm:items-end" @submit.prevent="saveIpCameraUrl">
        <label class="min-w-0 flex-1 text-sm text-gray-200">
          <span class="mb-1 block text-xs font-medium text-gray-400">IP camera URL</span>
          <input
            v-model="ipCameraUrl"
            type="text"
            inputmode="url"
            autocomplete="url"
            placeholder="rtsp://camera.local/stream"
            :disabled="settingsLoading || settingsSaving"
            class="w-full rounded border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600 focus:border-blue-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
          >
        </label>
        <button
          type="submit"
          :disabled="settingsLoading || settingsSaving"
          class="rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-blue-900"
        >
          {{ settingsSaving ? "Saving..." : "Save URL" }}
        </button>
      </form>

      <p v-if="settingsError" class="text-xs text-red-300" role="alert">
        {{ settingsError }}
      </p>
      <p v-else-if="saveMessage" class="text-xs text-green-300" role="status">
        {{ saveMessage }}
      </p>
    </section>

    <section class="space-y-3">
      <header class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 class="text-sm font-semibold uppercase tracking-wider text-gray-300">
            Camera display preferences
          </h3>
          <p class="mt-1 text-xs text-gray-400">
            Names, image orientation, and the hide flag persist with the machine (not just this browser).
          </p>
        </div>
        <button
          type="button"
          :disabled="devicesLoading"
          class="rounded bg-gray-700 px-3 py-1.5 text-xs font-semibold text-gray-200 transition-colors hover:bg-gray-600 disabled:cursor-not-allowed disabled:opacity-60"
          @click="store.fetchDevices()"
        >
          {{ devicesLoading ? "Refreshing..." : "Refresh Devices" }}
        </button>
      </header>

      <p v-if="devicesError" class="text-xs text-red-300" role="alert">
        {{ devicesError }}
      </p>

      <div
        v-if="!devicesLoading && devices.length === 0"
        class="rounded border border-dashed border-gray-700 bg-gray-900/40 p-6 text-center text-sm text-gray-500"
      >
        <p v-if="streamMessage" class="font-semibold text-amber-300">
          Camera unavailable
        </p>
        <p v-if="streamMessage" class="mt-2 text-xs text-gray-300">
          {{ streamMessage }}
        </p>
        <p v-else>
          No cameras were detected. Connect a USB camera or save an IP camera URL.
        </p>
      </div>

      <div
        v-else-if="!preferencesHydrated"
        class="rounded border border-dashed border-gray-700 bg-gray-900/40 p-6 text-center text-sm text-gray-500"
        aria-busy="true"
      >
        Loading preferences…
      </div>

      <ul v-else class="space-y-3">
        <li
          v-for="(device, index) in devices"
          :key="device.id"
          class="rounded-lg border border-gray-700 bg-gray-800/50 p-4"
        >
          <div class="flex flex-col gap-4 lg:flex-row lg:items-end">
            <div class="min-w-0 flex-1">
              <div class="mb-2 flex flex-wrap items-center gap-2">
                <span class="truncate text-sm font-semibold text-gray-100">
                  {{ device.name }}
                </span>
                <span class="rounded bg-gray-700 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-300">
                  {{ device.source }}
                </span>
              </div>
              <p class="mb-3 truncate font-mono text-xs text-gray-500" :title="device.id">
                {{ device.id }}
              </p>
              <label :for="`camera-custom-name-${index}`" class="block text-xs font-medium text-gray-400">
                Custom name
              </label>
              <input
                :id="`camera-custom-name-${index}`"
                type="text"
                :value="preferenceFor(device.id).customName"
                placeholder="Use hardware name"
                class="mt-1 w-full rounded border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
                @input="updateCustomName(device.id, $event)"
              >
            </div>

            <div class="flex flex-wrap gap-5 pb-2 lg:shrink-0">
              <label class="flex cursor-pointer select-none items-center gap-2 text-sm text-gray-200">
                <input
                  type="checkbox"
                  :checked="preferenceFor(device.id).flip"
                  class="h-5 w-5 rounded border-gray-600 bg-gray-900 text-blue-500 focus:ring-blue-500"
                  @change="updateBooleanPreference(device.id, 'flip', $event)"
                >
                Flip
              </label>
              <label class="flex cursor-pointer select-none items-center gap-2 text-sm text-gray-200">
                <input
                  type="checkbox"
                  :checked="preferenceFor(device.id).mirror"
                  class="h-5 w-5 rounded border-gray-600 bg-gray-900 text-blue-500 focus:ring-blue-500"
                  @change="updateBooleanPreference(device.id, 'mirror', $event)"
                >
                Mirror
              </label>
              <label class="flex cursor-pointer select-none items-center gap-2 text-sm text-gray-200">
                <input
                  type="checkbox"
                  :checked="preferenceFor(device.id).hidden"
                  class="h-5 w-5 rounded border-gray-600 bg-gray-900 text-blue-500 focus:ring-blue-500"
                  @change="updateBooleanPreference(device.id, 'hidden', $event)"
                >
                Hide from cycle
              </label>
            </div>

            <!-- Remove button: only IP cameras are user-removable from
                 this surface; USB cameras come and go with the host
                 hardware. The action clears the URL and drops the
                 preference row so the persisted settings stay clean. -->
            <div v-if="device.source === 'ip'" class="flex shrink-0">
              <button
                type="button"
                :title="`Remove ${device.id}`"
                class="rounded border border-red-800 bg-red-900/40 px-3 py-1.5 text-xs font-semibold text-red-200 transition-colors hover:bg-red-800 hover:text-white"
                @click="confirmRemove(device)"
              >
                Remove
              </button>
            </div>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>
