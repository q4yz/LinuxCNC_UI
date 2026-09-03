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
import BaseCard from "../ui/BaseCard.vue";
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

      </div>

      <!-- Right Column: flex-[2] tells it to take twice as much space as the left -->
      <div class="flex-[2] min-w-[600px] flex flex-col space-y-6">



          <BaseCard title="Toolpath" >
            <div class="flex-1 relative h-[600px]">
              <NgcCoordinateSystemViewer/>
            </div>
          </BaseCard>


        <ActivePrintWidget/>

        <div class="h-[300px]">
          <ConsolePanel/>
        </div>

        <CameraViewer/>

      </div>
    </div>
  </div>
</template>