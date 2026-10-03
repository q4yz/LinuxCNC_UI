<script setup lang="ts">
// Settings view — generated from the central settings registry.
//
// Every setting defined in ``settings/definitions/*`` appears here under
// its category, rendered with its own editor (``setting.component``) —
// no hand-written panel per module. Settings are stored by the system
// service (``/api/v1/settings``), so this page works while the machine
// backend is offline; only editors that need machine data (the camera
// device list) gate themselves.
//
// The "3D Viewer" tab is the exception: those are per-browser display
// preferences (localStorage), deliberately not shared between clients.
//
// Only the active tab is mounted (``v-if``), so critical settings are
// read fresh only when their tab is opened.

import { computed, ref, watch } from "vue";
import { settingsRegistry } from "../settings";
import SettingRow from "../settings/components/SettingRow.vue";
import ViewerSettingsPanel from "../components/viewer/ViewerSettingsPanel.vue";

const VIEWER_TAB = "3D Viewer";
// Preferred tab order; categories not listed follow alphabetically.
const CATEGORY_ORDER = ["Machine", "Macro Buttons", "Temperature", "Camera"];

const { categories, fetched } = settingsRegistry;

const tabs = computed(() => {
  const names = Object.keys(categories.value).sort((a, b) => {
    const ia = CATEGORY_ORDER.indexOf(a);
    const ib = CATEGORY_ORDER.indexOf(b);
    if (ia !== -1 || ib !== -1) return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    return a.localeCompare(b);
  });
  return [...names, VIEWER_TAB];
});

const activeTab = ref<string>("");
watch(
    tabs,
    (list) => {
      if (!list.includes(activeTab.value)) activeTab.value = list[0] ?? VIEWER_TAB;
    },
    { immediate: true },
);

const activeSettings = computed(() => categories.value[activeTab.value] ?? []);

const activeClasses = "bg-blue-600 text-white border-b-2 border-blue-400";
const inactiveClasses = "text-gray-400 hover:bg-gray-700 hover:text-gray-200 border-b-2 border-transparent";
</script>

<template>
  <div class="space-y-6">
    <header class="flex items-baseline justify-between">
      <h1 class="text-2xl font-bold">Settings</h1>
      <button
          v-if="!fetched"
          type="button"
          class="text-xs text-amber-300 underline"
          title="Stored values could not be loaded — the settings below show their defaults"
          data-testid="settings-retry"
          @click="settingsRegistry.fetchAll()"
      >
        Showing defaults — retry loading
      </button>
    </header>

    <div class="bg-gray-800 rounded-lg overflow-hidden">
      <nav class="flex flex-wrap border-b border-gray-700" role="tablist">
        <button
            v-for="tab in tabs"
            :key="tab"
            type="button"
            role="tab"
            class="px-4 py-3 text-sm font-medium transition-colors"
            :class="activeTab === tab ? activeClasses : inactiveClasses"
            :aria-selected="activeTab === tab"
            :data-testid="`settings-tab-${tab}`"
            @click="activeTab = tab"
        >
          {{ tab }}
        </button>
      </nav>

      <div v-if="activeTab === VIEWER_TAB" class="p-6" role="tabpanel">
        <ViewerSettingsPanel />
        <p class="mt-4 text-xs text-gray-500">Stored in this browser only (not shared with other clients).</p>
      </div>

      <div v-else class="p-6 space-y-3" role="tabpanel">
        <SettingRow v-for="setting in activeSettings" :key="setting.key" :setting="setting" />
        <p class="pt-2 text-xs text-gray-500">
          Stored on the machine (<code>/api/v1/settings</code>) and shared by every browser.
        </p>
      </div>
    </div>
  </div>
</template>
