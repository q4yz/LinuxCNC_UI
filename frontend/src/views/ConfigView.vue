<script setup lang="ts">
// Config page shell.
//
// Hosts the ``HttpsBanner`` that nudges operators off plain HTTP onto
// the nginx-served HTTPS origin (port 443), plus a small install guide
// that walks through trusting the mkcert root CA on a client device.
// The banner self-hides on HTTPS so the page is informative but quiet
// when the operator is already on the secure origin.

import HttpsBanner from '../components/HttpsBanner.vue'
import ActivePanel from "../components/machineconfig/ActivePanel.vue";
import MacroManagerPanel from "../components/macros/MacroManagerPanel.vue";
import McodeManagerPanel from "../components/macros/McodeManagerPanel.vue";
import UpdateManager from "../components/UpdateManager.vue";
import {useMachineConfigStore} from "../stores/machineconfigStore";
import {onMounted} from "vue";
import ProfilesExplorer from "../components/machineconfig/ProfilesExplorer.vue";
import MachinesExplorer from "../components/machineconfig/MachinesExplorer.vue";
import {openInEditor} from "../helpers/openInEditor";

const machineConfigStore = useMachineConfigStore()

// Used by the explorers to request an edit. Pushes the
// ``/editor?source=<source>&name=<path>`` URL; EditorView's
// ``watch`` detects the route change and loads the file.
function openEditor(source: string, path: string) {
  openInEditor({ source, name: path })
}

onMounted(() => {
  void machineConfigStore.loadAll()
})

</script>




<template>
  <!-- Replaced space-y-6 with flex and gap -->
  <div class="flex flex-col gap-6" data-test="config-view">

    <header class="flex items-baseline justify-between mb-2">
      <h1 class="text-2xl font-bold">Configuration</h1>
    </header>

    <!-- Added items-start to force top alignment -->
    <div class="grid grid-cols-1 gap-6 pb-8 xl:grid-cols-12 items-start">

      <!-- Replaced space-y-6 with flex flex-col gap-6 -->
      <section class="flex flex-col gap-6 xl:col-span-4">
        <HttpsBanner />
        <MacroManagerPanel />
        <McodeManagerPanel />
      </section>

      <!-- Replaced space-y-6 with flex flex-col gap-6 -->
      <section class="flex flex-col gap-6 xl:col-span-8">
        <UpdateManager />
        <ProfilesExplorer @edit="(path) => openEditor('profiles', path)" />
        <MachinesExplorer @edit="(path) => openEditor('machines', path)" />
        <ActivePanel />

      </section>

    </div>
  </div>
</template>

<style scoped>
</style>
