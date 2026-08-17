<script setup>
// Machineconfig module's top-level view. Hosts every panel that used
// to live in ``EditorView.vue``'s ``v-else`` branch — the surface is
// identical so existing CSS / column ratios carry over verbatim.
//
// Routing: the registry adds a ``/machineconfig`` route at boot
// (``router/index.js::registerModuleRoutes``) and ``App.vue`` mounts
// this component as the module's ``mainView``. ProfilesExplorer's
// ``@edit`` event pushes ``/editor?source=profiles&name=<path>`` via
// the shared :func:`openInEditor` helper — the universal editor
// contract (issue #132) is the only entry point into ``EditorView``.

import { onMounted } from 'vue'

import UpdateManager from '../../../components/UpdateManager.vue'
import DebugPanel from '../../../components/DebugPanel.vue'
import CompilerPanel from './CompilerPanel.vue'
import CompiledOutputViewer from './CompiledOutputViewer.vue'
import DeploymentPanel from './DeploymentPanel.vue'
import ProfilesExplorer from './ProfilesExplorer.vue'
import ActivePanel from './ActivePanel.vue'
import MacroManagerPanel from '../../macros/components/MacroManagerPanel.vue'
import McodeManagerPanel from '../../macros/components/McodeManagerPanel.vue'
import { useMachineConfigStore } from '../store'
import { openInEditor } from '../../../helpers/openInEditor'

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
