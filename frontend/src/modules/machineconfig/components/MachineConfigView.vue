<script setup>
// Machineconfig module's top-level view. Hosts every panel that used
// to live in ``EditorView.vue``'s ``v-else`` branch — the surface is
// identical so existing CSS / column ratios carry over verbatim.
//
// Routing: the registry adds a ``/machineconfig`` route at boot
// (``router/index.js::registerModuleRoutes``) and ``App.vue`` mounts
// this component as the module's ``mainView``. The legacy
// ``/config/:filename?`` route still drives the per-file editor in
// ``EditorView.vue`` — ProfilesExplorer's ``@edit`` event pushes to
// ``name: 'config'`` and the editor overlay renders inside the App
// shell, just like the old behaviour.

import { onMounted } from 'vue'
import { useRouter } from 'vue-router'

import UpdateManager from '../../../components/UpdateManager.vue'
import DebugPanel from '../../../components/DebugPanel.vue'
import CompilerPanel from './CompilerPanel.vue'
import CompiledOutputViewer from './CompiledOutputViewer.vue'
import DeploymentPanel from './DeploymentPanel.vue'
import ProfilesExplorer from './ProfilesExplorer.vue'
import ActivePanel from './ActivePanel.vue'
import MacroManagerPanel from '../../macros/components/MacroManagerPanel.vue'
import McodeManagerPanel from '../../macros/components/McodeManagerPanel.vue'
import { useMachineConfigStore } from '../store.js'

const machineConfigStore = useMachineConfigStore()
const router = useRouter()

// Used by ProfilesExplorer to request an edit. This strictly
// changes the URL; the editor route's ``watch`` (EditorView.vue)
// detects the URL change and loads the file.
function openEditor(path) {
  router.push({ name: 'config', params: { filename: path } })
    .catch(err => console.error('Router error on open:', err))
}

onMounted(() => {
  void machineConfigStore.loadAll()
})
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
        <ProfilesExplorer @edit="openEditor" />

        <div class="space-y-6">
          <CompiledOutputViewer />
          <DeploymentPanel />
        </div>
      </div>

      <ActivePanel />

      <!-- Macros & NGC section. The macros module owns its own
           CRUD via ``useMacrosStore()``; the panel mounts that
           store on first use so an unrelated Machine-Config user
           pays no startup cost. Shared with the machineconfig
           surface because that is where operators usually discover
           the macros UI. -->
      <MacroManagerPanel />

      <!-- M-codes sub-panel. Lives in the same module (shared
           Pinia store) but operates on the dedicated
           ``machine_config/m_codes/`` root. The Edit button
           deep-links into the universal editor with the bare
           ``M<num>`` token so the same CodeMirror surface that
           handles profiles and ``.macro`` files also handles
           M-codes. -->
      <McodeManagerPanel />
    </section>
  </div>
</template>
