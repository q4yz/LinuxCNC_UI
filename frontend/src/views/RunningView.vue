<script setup lang="ts">
import NgcCoordinateSystemViewer from '../components/NgcCoordinateSystemViewer.vue'
import ConsolePanel from '../components/ConsolePanel.vue'
import ActivePrintWidget from '../components/ActivePrintWidget.vue'
import TemperaturePanel from '../components/temperature/TemperaturePanel.vue'
import DroPanel from '../components/machine/DroPanel.vue'
</script>

<template>
  <div class="h-full overflow-y-auto pr-2">
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 pb-8">

      <!-- Left Column: Job Status & Machine State -->
      <div class="lg:col-span-4 xl:col-span-4 flex flex-col space-y-6">
        <ActivePrintWidget />
        <DroPanel />
        <TemperaturePanel />
      </div>

      <!-- Right Column: Toolpath & Logging -->
      <div class="lg:col-span-8 xl:col-span-8 flex flex-col space-y-6">

        <!-- Toolpath Viewer: Responsive height scaling -->
        <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden flex flex-col h-[400px] lg:h-[60vh] shrink-0">
          <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600">
            <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">Toolpath</h2>
          </div>
          <div class="flex-1 relative">
            <NgcCoordinateSystemViewer />
          </div>
        </div>

        <div class="h-[300px]">
          <ConsolePanel />
        </div>

      </div>

    </div>
  </div>
</template>