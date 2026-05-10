<script setup>
// This view acts as a wrapper containing the main UI grid components.
// We import the modular panels from the components directory.
import DroPanel from '../components/DroPanel.vue'
import JogControls from '../components/JogControls.vue'
import GCodeViewer from '../components/GCodeViewer.vue'
import ConsolePanel from '../components/ConsolePanel.vue'
import TemperaturePanel from '../components/TemperaturePanel.vue'
import DebugPanel from '../components/DebugPanel.vue'
import { Camera } from 'three/src/Three.Core.js'
import CameraPanel from '../components/CameraPanel.vue'
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
          <CameraPanel />
      

      </div>

    </div>
  </div>
</template>
