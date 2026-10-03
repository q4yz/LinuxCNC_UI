<script setup lang="ts">
// Editor for the IP camera URL (critical: read fresh by SettingRow).
// Saving also seeds a preferences row for the new camera so it can be
// renamed/oriented right away, then refreshes the device list. The
// device refresh needs the machine backend; the save itself does not.
import { computed, ref } from "vue";
import { BaseButton } from "../../ui";
import { useCameraStore } from "../../stores/cameraStore";
import type { IpCameraUrlSetting } from "../types/IpCameraUrlSetting";

const props = defineProps<{ setting: IpCameraUrlSetting }>();
const cameraStore = useCameraStore();

const draft = ref<string | null>(null);
const shown = computed(() => draft.value ?? props.setting.value ?? "");
const saving = ref(false);
const message = ref("");
const error = ref("");

async function save() {
  const url = shown.value.trim();
  error.value = props.setting.problem(url) ?? "";
  message.value = "";
  if (error.value) return;

  saving.value = true;
  try {
    const result = await props.setting.save(url);
    if (result.failed) {
      error.value = "Saving the URL failed — see the console.";
      return;
    }
    draft.value = null;
    await cameraStore.ensurePreference(url);
    message.value = url ? "IP camera URL saved." : "IP camera removed.";
    void cameraStore.fetchDevices();
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <form class="flex w-full max-w-xl flex-col gap-2" @submit.prevent="save">
    <div class="flex gap-2">
      <input
          :value="shown"
          type="text"
          inputmode="url"
          autocomplete="url"
          :placeholder="setting.constraints.placeholder"
          :disabled="!setting.isLoaded || saving"
          :title="setting.isLoaded ? undefined : `${setting.label}: loading from the backend`"
          :data-testid="`setting-${setting.key}`"
          class="min-w-0 flex-1 bg-gray-900 border border-gray-600 rounded px-3 py-2 text-gray-100 placeholder-gray-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
          @input="draft = ($event.target as HTMLInputElement).value"
      />
      <BaseButton type="submit" variant="primary" :loading="saving" :disabled="!setting.isLoaded">
        Save URL
      </BaseButton>
    </div>
    <p v-if="error" class="text-xs text-red-300" role="alert">{{ error }}</p>
    <p v-else-if="message" class="text-xs text-green-300" role="status">{{ message }}</p>
  </form>
</template>
