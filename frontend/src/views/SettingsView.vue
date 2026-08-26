<script setup>
// Settings shell. Each panel that contributes a Settings tab is
// imported statically and rendered as a hard dependency. The
// registry-driven ``settingsPanels()`` walker is gone — every
// panel below must compile to ship.

import CameraSettings from '../components/camera/CameraSettings.vue'
import MachineSettingsPanel from '../components/machine/MachineSettingsPanel.vue'
import TemperatureSettingsPanel from '../components/temperature/TemperatureSettingsPanel.vue'

function apiBaseUrl(moduleId) {
  return `/api/v1/modules/${moduleId}/settings`
}
</script>

<template>
  <div class="space-y-6">
    <header class="flex items-baseline justify-between">
      <h1 class="text-2xl font-bold">Settings</h1>
    </header>

    <div class="bg-gray-800 rounded-lg overflow-hidden">
      <nav class="flex border-b border-gray-700">
        <button
          class="px-4 py-3 text-sm font-medium transition-colors bg-blue-600 text-white border-b-2 border-blue-400"
          data-testid="settings-tab-camera"
        >
          Camera
        </button>
        <button
          class="px-4 py-3 text-sm font-medium transition-colors text-gray-400 hover:bg-gray-700 hover:text-gray-200"
          data-testid="settings-tab-machineconfig"
        >
          Machine Config
        </button>
        <button
          class="px-4 py-3 text-sm font-medium transition-colors text-gray-400 hover:bg-gray-700 hover:text-gray-200"
          data-testid="settings-tab-temperature"
        >
          Temperature
        </button>
      </nav>

      <div class="p-6">
        <h2 class="text-lg font-semibold text-gray-200">Camera settings</h2>
        <CameraSettings class="mt-4" />
        <p class="mt-4 text-xs text-gray-500">
          Persisted at: <code>{{ apiBaseUrl('camera') }}</code>
        </p>
      </div>

      <div class="p-6 border-t border-gray-700">
        <h2 class="text-lg font-semibold text-gray-200">Machine Config settings</h2>
        <MachineSettingsPanel class="mt-4" />
        <p class="mt-4 text-xs text-gray-500">
          Persisted at: <code>{{ apiBaseUrl('machineconfig') }}</code>
        </p>
      </div>

      <div class="p-6 border-t border-gray-700">
        <h2 class="text-lg font-semibold text-gray-200">Temperature settings</h2>
        <TemperatureSettingsPanel class="mt-4" />
        <p class="mt-4 text-xs text-gray-500">
          Persisted at: <code>{{ apiBaseUrl('temperature') }}</code>
        </p>
      </div>
    </div>
  </div>
</template>