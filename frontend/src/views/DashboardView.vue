<script setup>
// Dashboard composition. Each module-owned panel is loaded via
// ``defineAsyncComponent`` so removing the corresponding
// ``frontend/src/modules/<id>/`` folder leaves the build intact
// (MODULE_SYSTEM_ROADMAP.md § 12 Gotcha #1).
//
// The dashboard then reads ``registry.modules`` to decide whether to
// render the panel at all. The legacy static imports were dropped
// because they would re-introduce the very "deleting a folder breaks
// the build" failure mode the module system is designed to avoid.
import { defineAsyncComponent, computed } from 'vue'
import registry from '../core/modules/registry'
import DroPanel from '../components/DroPanel.vue'
import JogControls from '../components/JogControls.vue'
import GCodeViewer from '../components/GCodeViewer.vue'
import ConsolePanel from '../components/ConsolePanel.vue'
import TemperaturePanel from '../components/TemperaturePanel.vue'
import DebugPanel from '../components/DebugPanel.vue'

// Lazy camera panel. The ``() => import(...)`` callback is only
// evaluated if the dashboard actually renders ``<CameraPanel />``,
// which only happens when the module is mounted.
const CameraPanel = defineAsyncComponent(
  () => import('../modules/camera/components/CameraPanel.vue'),
)

// Track whether each module is currently mounted so the dashboard
// can render placeholder slots in their place when missing. Today
// only the camera uses this — but having the pattern in place means
// the temperature migration can adopt the same shape without
// re-litigating the layout.
const cameraMounted = computed(() => registry.modules.has('camera'))
</script>

<template>
  <div class="h-full overflow-y-auto pr-2">
    <!-- Grid Layout for Panels -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 pb-8">

      <!-- Left Column: DRO, Heater & Controls -->
      <div class="col-span-1 flex flex-col space-y-6">
        <DroPanel />
        <TemperaturePanel />
        <JogControls />
      </div>

      <!-- Right Column: 3D Viewer & Console -->
      <div class="lg:col-span-2 flex flex-col space-y-6">

        <!-- 3D Viewer -->
        <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden flex flex-col h-[400px] shrink-0">
          <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600">
            <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">Toolpath</h2>
          </div>
          <div class="flex-1 relative">
            <GCodeViewer />
          </div>
        </div>

        <!-- Terminal / Console -->
        <div class="h-[300px]">
          <ConsolePanel />

        </div>

        <!--
          Camera slot: rendered only when the camera module is mounted.
          ``v-if`` + ``CameraPanel`` as an async component keeps the
          camera bundle out of the initial chunk (Gotcha #1) and lets
          us delete ``frontend/src/modules/camera/`` cleanly.
        -->
        <div v-if="cameraMounted" class="lg:col-span-2">
          <CameraPanel />
        </div>

      </div>

    </div>
  </div>
</template>