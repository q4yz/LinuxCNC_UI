<script setup lang="ts">
import ActivePrintWidget from '../components/ActivePrintWidget.vue'
import ToolPanel from "../components/tools/ToolPanel.vue";
import CameraViewer from "../components/camera/CameraViewer.vue";
import AxisSpeedControl from "../components/machine/AxisSpeedControl.vue";
</script>

<template>
  <div class="h-full overflow-y-auto pr-2">
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 pb-8">

      <!-- Left Column: Job Status & Machine State -->
      <div class="lg:col-span-4 xl:col-span-4 flex flex-col space-y-6">
        <ActivePrintWidget />
        <AxisSpeedControl />
        <ToolPanel />
      </div>

      <!-- Right Column: Toolpath & Logging -->
      <div class="lg:col-span-8 xl:col-span-8 flex flex-col space-y-6">

        <CameraViewer/>



      </div>

    </div>
  </div>
</template>