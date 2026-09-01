<script setup lang="ts">
// Machineconfig top-level view. Hosts every panel that used to live
// in ``EditorView.vue``'s ``v-else`` branch — the surface is
// identical so existing CSS / column ratios carry over verbatim.
//
// Routing: ``router/index.ts`` declares the ``/machineconfig`` route
// and maps it to this component. ProfilesExplorer's ``@edit`` event
// pushes ``/editor?source=profiles&name=<path>`` via the shared
// :func:`openInEditor` helper — the universal editor contract
// (issue #132) is the only entry point into ``EditorView``.

import { onMounted } from 'vue'

import UpdateManager from '../components/UpdateManager.vue'
import DebugPanel from '../components/DebugPanel.vue'
import CompilerPanel from '../components/machineconfig/CompilerPanel.vue'
import CompiledOutputViewer from '../components/machineconfig/CompiledOutputViewer.vue'
import DeploymentPanel from '../components/machineconfig/DeploymentPanel.vue'
import ProfilesExplorer from '../components/machineconfig/ProfilesExplorer.vue'
import ActivePanel from '../components/machineconfig/ActivePanel.vue'
import MacroManagerPanel from '../components/macros/MacroManagerPanel.vue'
import McodeManagerPanel from '../components/macros/McodeManagerPanel.vue'
import { useMachineConfigStore } from '../stores/machineconfigStore'
import { openInEditor } from '../helpers/openInEditor'

const machineConfigStore = useMachineConfigStore()

// Used by ProfilesExplorer to request an edit. Pushes the
// ``/editor?source=profiles&name=<path>`` URL; EditorView's
// ``watch`` detects the route change and loads the file.
function openEditor(path) {
  openInEditor({ source: 'profiles', name: path })
}

onMounted(() => {
  void machineConfigStore.loadAll()
})
</script>

<template>
  <div class="grid grid-cols-1 gap-6 pb-8 xl:grid-cols-12">
    <section class="space-y-6 xl:col-span-4">

    </section>

    <section class="space-y-6 xl:col-span-8">
      <CompilerPanel />

      <div class="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <ProfilesExplorer @edit="openEditor" />

        <div class="space-y-6">
          <CompiledOutputViewer />
          <DeploymentPanel />
        </div>
      </div>


    </section>
  </div>
</template>
