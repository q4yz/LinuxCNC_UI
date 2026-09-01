<script setup lang="ts">
// Machineconfig top-level view — three sections:
//
//   Profiles  — the profile explorer; each ``.cfg`` row carries a
//               Generate button that creates the machine template set.
//   Machines  — browse the generated machine template sets
//               (``<machine>/configs/...``); files are editable
//               templates.
//   Active    — the currently running machine's files (read-only;
//               switching machines happens outside the UI by
//               starting ``linuxcnc <machine>.ini``).
//
// The deprecated Klipper compiler flow is no longer rendered here;
// the backend keeps the old endpoints during the transition.
//
// Routing: ``router/index.ts`` declares the ``/machineconfig`` route
// and maps it to this component. Both explorers push
// ``/editor?source=<source>&name=<path>`` via the shared
// :func:`openInEditor` helper — the universal editor contract
// (issue #132) is the only entry point into ``EditorView``.

import { onMounted } from 'vue'

import ActivePanel from '../components/machineconfig/ActivePanel.vue'
import MachinesExplorer from '../components/machineconfig/MachinesExplorer.vue'
import ProfilesExplorer from '../components/machineconfig/ProfilesExplorer.vue'
import { useMachineConfigStore } from '../stores/machineconfigStore'
import { openInEditor } from '../helpers/openInEditor'

const machineConfigStore = useMachineConfigStore()

// Used by the explorers to request an edit. Pushes the
// ``/editor?source=<source>&name=<path>`` URL; EditorView's
// ``watch`` detects the route change and loads the file.
function openEditor(source, path) {
  openInEditor({ source, name: path })
}

onMounted(() => {
  void machineConfigStore.loadAll()
})
</script>

<template>
  <div class="grid grid-cols-1 gap-6 pb-8 xl:grid-cols-12">
    <section class="space-y-6 xl:col-span-4">
      <ProfilesExplorer @edit="(path) => openEditor('profiles', path)" />
    </section>

    <section class="space-y-6 xl:col-span-4">
      <MachinesExplorer @edit="(path) => openEditor('machines', path)" />
    </section>

    <section class="space-y-6 xl:col-span-4">
      <ActivePanel />
    </section>
  </div>
</template>
