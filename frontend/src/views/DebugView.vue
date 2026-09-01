<script setup lang="ts">

import ActivePanel from "../components/machineconfig/ActivePanel.vue";
import ProfilesExplorer from "../components/machineconfig/ProfilesExplorer.vue";
import DeploymentPanel from "../components/machineconfig/DeploymentPanel.vue";
import MacroManagerPanel from "../components/macros/MacroManagerPanel.vue";
import McodeManagerPanel from "../components/macros/McodeManagerPanel.vue";
import UpdateManager from "../components/UpdateManager.vue";
import DebugPanel from "../components/DebugPanel.vue";
import CompilerPanel from "../components/machineconfig/CompilerPanel.vue";
import CompiledOutputViewer from "../components/machineconfig/CompiledOutputViewer.vue";
</script>

<template>

  <header class="flex items-baseline justify-between">
    <h1 class="text-2xl font-bold">Debug</h1>
  </header>

  <div class="grid grid-cols-1 gap-6 pb-8 xl:grid-cols-12">
    <section class="space-y-6 xl:col-span-4">
      <DebugPanel />
    </section>

    <section class="space-y-6 xl:col-span-8">

      <ActivePanel />





    </section>
  </div>


</template>

<style scoped>

</style>