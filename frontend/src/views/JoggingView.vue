<script setup lang="ts" >
import DroPanel from '../components/machine/DroPanel.vue'
import JogControls from '../components/machine/JogControls.vue'
import ToolPanel from '../components/tools/ToolPanel.vue'
import MacroPanel from '../components/macros/MacroPanel.vue'
import McodePanel from '../components/macros/McodePanel.vue'
import CameraViewer from '../components/camera/CameraViewer.vue'
</script>

<template>
  <div class="h-full overflow-y-auto pr-2">
    <!-- Mobile: 1 column. Desktop (lg): 12-column grid. -->
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 pb-8">

      <!-- Left Column: Manual Controls (Takes up 5/12 on large screens) -->
      <div class="lg:col-span-5 xl:col-span-4 flex flex-col space-y-6">
        <DroPanel />
        <JogControls />
        <ToolPanel />
        <MacroPanel />
        <McodePanel />
      </div>

      <!-- Right Column: Visualization & Alignment (Takes up 7/12 on large screens) -->
      <div class="lg:col-span-7 xl:col-span-8 flex flex-col space-y-6">
        <CameraViewer />
      </div>

    </div>
  </div>
</template>