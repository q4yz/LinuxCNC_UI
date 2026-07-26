<script setup>
import { ref, onMounted } from 'vue'
import registry from './core/modules/registry'
import { useMachineStore } from './stores/machine-compat'
import AppSidebar from './components/AppSidebar.vue'
import DashboardView from './views/DashboardView.vue'
import FilesView from './views/FilesView.vue'
import ConfigView from './views/ConfigView.vue'
import SettingsView from './views/SettingsView.vue'
import ConfigEditor from './components/ConfigEditor.vue'

// ``useMachineStore`` is supplied by the optional compatibility adapter.
// When the machine module is mounted, the module registers its real store
// before the app mounts; when it is absent, the adapter is intentionally
// inert so the shell can still render its placeholders.
const store = useMachineStore()
const currentView = ref('dashboard')
const editorFile = ref(null)
const editorReadOnly = ref(false)

onMounted(() => {
  // The registry is booted before mount. Keep this guarded fallback for
  // deployments that explicitly exclude the machine module.
  if (!registry.modules.has('machine')) {
    store.connect()
  }

  // Parse URL parameters to check if editor should be opened
  const params = new URLSearchParams(window.location.search)
  if (params.has('editor')) {
    editorFile.value = params.get('editor')
  }
  editorReadOnly.value = params.get('readonly') === '1' || params.get('readonly') === 'true'
})
</script>

<template>
  <ConfigEditor v-if="editorFile" :filename="editorFile" :read-only="editorReadOnly" />
  <div v-else class="flex h-screen overflow-hidden bg-gray-900 text-white font-sans">

    <!-- Sidebar Navigation -->
    <AppSidebar :currentView="currentView" @navigate="(view) => currentView = view" />

    <!-- Main Content Area -->
    <main class="flex-1 overflow-y-auto p-4 lg:p-8">
      <DashboardView v-if="currentView === 'dashboard'" />
      <FilesView v-else-if="currentView === 'files'" />
      <ConfigView v-else-if="currentView === 'config'" />
      <SettingsView v-else-if="currentView === 'settings'" />
    </main>

  </div>
</template>
