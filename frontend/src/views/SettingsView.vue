<script setup lang="ts">
// Settings shell. Each panel that contributes a Settings tab is
// imported statically and rendered as a hard dependency. The
// registry-driven ``settingsPanels()`` walker is gone — every
// panel below must compile to ship.
//
// The tab bar used to be purely decorative: all three panels
// (Camera/Machine Config/Temperature) rendered simultaneously,
// stacked one under another, regardless of which tab looked
// "active". Each one fetches its own settings on mount
// (CameraSettings, MachineSettingsPanel both do; see their own
// onMounted), so opening this page fired three independent
// settings round-trips and mounted three independent component
// trees at once — the same "everything mounts together" pattern
// the dashboard had, just here every time, not just once per
// session. ``activeTab`` + ``v-if`` (not ``v-show``) means only the
// selected panel's component is ever mounted; the other two don't
// exist in the DOM and never fetch anything until the operator
// actually switches to them.

import { ref } from 'vue'
import CameraSettings from '../components/camera/CameraSettings.vue'
import MachineSettingsPanel from '../components/machine/MachineSettingsPanel.vue'
import TemperatureSettingsPanel from '../components/temperature/TemperatureSettingsPanel.vue'
import ViewerSettingsPanel from '../components/viewer/ViewerSettingsPanel.vue'
import MachineGate from '../components/machine/MachineGate.vue'

function apiBaseUrl(moduleId: string) {
  return `/api/v1/modules/${moduleId}/settings`
}

type SettingsTab = 'camera' | 'machineconfig' | 'temperature' | 'viewer'

const TABS: Array<{ id: SettingsTab; label: string }> = [
  { id: 'camera', label: 'Camera' },
  { id: 'machineconfig', label: 'Machine Config' },
  { id: 'temperature', label: 'Temperature' },
  { id: 'viewer', label: '3D Viewer' },
]

const activeTab = ref<SettingsTab>('camera')

const activeClasses = 'bg-blue-600 text-white border-b-2 border-blue-400'
const inactiveClasses = 'text-gray-400 hover:bg-gray-700 hover:text-gray-200 border-b-2 border-transparent'
</script>

<template>
  <div class="space-y-6">
    <header class="flex items-baseline justify-between">
      <h1 class="text-2xl font-bold">Settings</h1>
    </header>

    <div class="bg-gray-800 rounded-lg overflow-hidden">
      <nav class="flex border-b border-gray-700" role="tablist">
        <button
          v-for="tab in TABS"
          :key="tab.id"
          type="button"
          role="tab"
          class="px-4 py-3 text-sm font-medium transition-colors"
          :class="activeTab === tab.id ? activeClasses : inactiveClasses"
          :aria-selected="activeTab === tab.id"
          :data-testid="`settings-tab-${tab.id}`"
          @click="activeTab = tab.id"
        >
          {{ tab.label }}
        </button>
      </nav>

      <div v-if="activeTab === 'camera'" class="p-6" role="tabpanel">
        <h2 class="text-lg font-semibold text-gray-200">Camera settings</h2>
        <MachineGate label="Camera settings">
          <CameraSettings class="mt-4" />
        </MachineGate>
        <p class="mt-4 text-xs text-gray-500">
          Persisted at: <code>{{ apiBaseUrl('camera') }}</code>
        </p>
      </div>

      <div v-else-if="activeTab === 'machineconfig'" class="p-6" role="tabpanel">
        <h2 class="text-lg font-semibold text-gray-200">Machine Config settings</h2>
        <MachineGate label="Machine settings">
          <MachineSettingsPanel class="mt-4" />
        </MachineGate>
        <p class="mt-4 text-xs text-gray-500">
          Persisted at: <code>{{ apiBaseUrl('machineconfig') }}</code>
        </p>
      </div>

      <div v-else-if="activeTab === 'temperature'" class="p-6" role="tabpanel">
        <h2 class="text-lg font-semibold text-gray-200">Temperature settings</h2>
        <MachineGate label="Temperature settings">
          <TemperatureSettingsPanel class="mt-4" />
        </MachineGate>
        <p class="mt-4 text-xs text-gray-500">
          Persisted at: <code>{{ apiBaseUrl('temperature') }}</code>
        </p>
      </div>

      <!-- Not machine-gated: both controls here are client-side
           localStorage preferences, not backend-persisted settings —
           there's nothing to wait on the machine backend for. -->
      <div v-else-if="activeTab === 'viewer'" class="p-6" role="tabpanel">
        <h2 class="text-lg font-semibold text-gray-200">3D Viewer settings</h2>
        <ViewerSettingsPanel class="mt-4" />
        <p class="mt-4 text-xs text-gray-500">
          Stored in this browser only (not synced to the machine).
        </p>
      </div>
    </div>
  </div>
</template>
