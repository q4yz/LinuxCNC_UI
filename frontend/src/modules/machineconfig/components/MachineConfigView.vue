<script setup>
// MachineConfigView — composes the four machineconfig panels into a
// single dashboard:
//
//   ┌─────────────────────────────────────────────────────────────────┐
//   │ CompilerPanel                                                   │
//   ├────────────────────────────────────────────┬────────────────────┤
//   │ ProfilesExplorer                           │ CompiledOutputViewer│
//   │                                            ├────────────────────┤
//   │                                            │ DeploymentPanel     │
//   ├────────────────────────────────────────────┴────────────────────┤
//   │ ActivePanel                                                    │
//   └─────────────────────────────────────────────────────────────────┘
//
// The view is exported as the module's primary component (see
// ``frontend/src/modules/machineconfig/index.js``).

import { onMounted } from "vue";
import ProfilesExplorer from "./ProfilesExplorer.vue";
import CompilerPanel from "./CompilerPanel.vue";
import CompiledOutputViewer from "./CompiledOutputViewer.vue";
import DeploymentPanel from "./DeploymentPanel.vue";
import ActivePanel from "./ActivePanel.vue";
import { useMachineConfigStore } from "../store.js";

const store = useMachineConfigStore();

onMounted(async () => {
  // The module's ``onLoad`` already kicked off the first load, but
  // a hard refresh (e.g. when the user toggles the sidebar back
  // onto the page) needs to fetch again.
  await store.loadAll();
});
</script>

<template>
  <div class="space-y-6 pb-8">
    <CompilerPanel />

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <ProfilesExplorer />
      <div class="space-y-6">
        <CompiledOutputViewer />
        <DeploymentPanel />
      </div>
    </div>

    <ActivePanel />
  </div>
</template>