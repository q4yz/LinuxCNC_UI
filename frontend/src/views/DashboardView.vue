<script setup lang="ts">
// Dashboard composition. Each domain panel is imported statically
// and rendered as a direct dependency. The previous registry-driven
// ``registry.modules.has(...)`` gates are gone — every panel below
// is required at build time.
//
// Machine-level panels are wrapped in ``<MachineGate>``: they only
// mount (and only generate network traffic) while the machine
// backend (:8000) is confirmed reachable. The console stays
// ungated — it also carries system-side rows and the offline
// explanation itself.

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
import MachineGate from "../components/machine/MachineGate.vue";
import BaseCard from "../ui/BaseCard.vue";

defineOptions({ name: 'DashboardView' })
</script>

<template>
  <div class="h-full overflow-y-auto pr-2">
    <!-- Changed from grid to flex flex-wrap -->
    <div class="flex flex-wrap gap-6 pb-8">

      <!-- Left Column: flex-1 tells it to take 1 part space, but NEVER go below 570px -->
      <div class="flex-1 min-w-[min(100%,570px)] flex flex-col space-y-6">

        <MachineGate label="Machine">
          <PowerOn/>
        </MachineGate>

        <MachineGate label="DRO">
          <DroPanel/>
        </MachineGate>

        <MachineGate label="Jog">
          <JogControls/>
        </MachineGate>

        <MachineGate label="Tools">
          <ToolPanel/>
        </MachineGate>

        <MachineGate label="Temperature">
          <TemperaturePanel/>
        </MachineGate>

      </div>

      <!-- Right Column: flex-[2] tells it to take twice as much space as the left -->
      <div class="flex-[2] min-w-[600px] flex flex-col space-y-6">



          <BaseCard title="Toolpath" >
            <!-- The actual 3D viewer is a single instance shared with
                 JoggingView, owned by App.vue, and moved here via
                 Teleport while this view is active (see App.vue) —
                 this div is just the slot it's teleported into. -->
            <div id="toolpath-slot-dashboard" class="flex-1 relative h-[600px]"></div>
          </BaseCard>


        <MachineGate label="Job status">
          <ActivePrintWidget/>
        </MachineGate>

        <div class="h-[300px]">
          <ConsolePanel/>
        </div>

        <!-- Camera: the gate's v-if physically unmounts the MJPEG
             <img> when the machine goes offline, aborting a hung
             stream instead of leaving the browser waiting on a
             dead connection. -->
        <MachineGate label="Camera">
          <CameraViewer/>
        </MachineGate>

      </div>
    </div>
  </div>
</template>
