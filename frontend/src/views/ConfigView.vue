<script setup>
import { onMounted } from 'vue';
import DebugPanel from '../components/DebugPanel.vue';
import UpdateManager from '../components/UpdateManager.vue';
import { useMachineConfigStore } from '../modules/machineconfig/store.js';
import ProfilesExplorer from '../modules/machineconfig/components/ProfilesExplorer.vue';
import CompilerPanel from '../modules/machineconfig/components/CompilerPanel.vue';
import CompiledOutputViewer from '../modules/machineconfig/components/CompiledOutputViewer.vue';
import DeploymentPanel from '../modules/machineconfig/components/DeploymentPanel.vue';
import ActivePanel from '../modules/machineconfig/components/ActivePanel.vue';

const machineConfigStore = useMachineConfigStore();

onMounted(() => {
  void machineConfigStore.loadAll();
});
</script>

<template>
  <div class="grid grid-cols-1 gap-6 pb-8 xl:grid-cols-12">
    <section class="space-y-6 xl:col-span-4">
      <UpdateManager />

      <DebugPanel />
    </section>

    <section class="space-y-6 xl:col-span-8">
      <CompilerPanel />

      <div class="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <ProfilesExplorer />

        <div class="space-y-6">
          <CompiledOutputViewer />
          <DeploymentPanel />
        </div>
      </div>

      <ActivePanel />
    </section>
  </div>
</template>
