<script setup lang="ts">
// Dashboard composition. Each domain panel is imported statically
// and rendered as a direct dependency. The previous registry-driven
// ``registry.modules.has(...)`` gates are gone — every panel below
// is required at build time.

import NgcCoordinateSystemViewer from '../components/NgcCoordinateSystemViewer.vue'
import ConsolePanel from '../components/ConsolePanel.vue'
import DebugPanel from '../components/DebugPanel.vue'
import ActivePrintWidget from '../components/ActivePrintWidget.vue'

import CameraViewer from '../components/camera/CameraViewer.vue'
import TemperaturePanel from '../components/temperature/TemperaturePanel.vue'
import DroPanel from '../components/machine/DroPanel.vue'
import JogControls from '../components/machine/JogControls.vue'
import ToolPanel from '../components/tools/ToolPanel.vue'
import MacroPanel from '../components/macros/MacroPanel.vue'
import McodePanel from '../components/macros/McodePanel.vue'
import PowerOn from "../components/machine/PowerOn.vue";
</script>

<template>
  <div class="h-full overflow-y-auto pr-2">
    <!-- Changed from grid to flex flex-wrap -->
    <div class="flex flex-wrap gap-6 pb-8">

      <!-- Left Column: flex-1 tells it to take 1 part space, but NEVER go below 570px -->
      <div class="flex-1 min-w-[min(100%,570px)] flex flex-col space-y-6">

        <PowerOn/>

        <DroPanel/>

        <JogControls/>

        <ToolPanel/>

        <TemperaturePanel/>

<!--        <MacroPanel/>-->

<!--        <McodePanel/>-->

      </div>

      <!-- Right Column: flex-[2] tells it to take twice as much space as the left -->
      <!-- min-w-[600px] ensures the 3D viewer doesn't get crushed -->
      <div class="flex-[2] min-w-[600px] flex flex-col space-y-6">

        <!-- ActivePrintWidget surfaces the current program (or the five
             newest G-code files when idle) and the pause/stop controls,
             so the operator does not have to leave the dashboard while
             a print is running. -->


        <div
            class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden flex flex-col h-[600px] shrink-0">
          <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600">
            <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">Toolpath</h2>
          </div>
          <div class="flex-1 relative">
            <NgcCoordinateSystemViewer/>
          </div>
        </div>

        <ActivePrintWidget/>

        <div class="h-[300px]">
          <ConsolePanel/>
        </div>

        <CameraViewer/>

      </div>

    </div>
  </div>
</template>