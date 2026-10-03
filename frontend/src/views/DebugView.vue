<script setup lang="ts">

import DebugPanel from "../components/DebugPanel.vue";
import HalPinStatePanel from "../components/debug/HalPinStatePanel.vue";
import MachineGate from "../components/machine/MachineGate.vue";

</script>

<template>

  <header class="flex items-baseline justify-between">
    <h1 class="text-2xl font-bold">Debug</h1>
  </header>

  <div class="grid grid-cols-1 gap-6 pb-8">
    <section class="space-y-6">
      <MachineGate label="Telemetry debug">
        <DebugPanel />
      </MachineGate>
      <!-- Pin list + values come from the machine backend (HAL). -->
      <MachineGate label="HAL pins">
        <HalPinStatePanel />
      </MachineGate>
    </section>
  </div>


</template>

<style scoped>

</style>