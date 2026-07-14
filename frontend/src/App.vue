<script setup>
import { ref, onMounted } from 'vue'
import { useMachineStore } from './stores/machine'
import AppSidebar from './components/AppSidebar.vue'
import DashboardView from './views/DashboardView.vue'
import FilesView from './views/FilesView.vue'
import ConfigView from './views/ConfigView.vue'
import ConfigEditor from './components/ConfigEditor.vue'

const store = useMachineStore()
const currentView = ref('dashboard')
const editorFile = ref(null)
const editorReadOnly = ref(false)

onMounted(() => {
  store.connect()
  
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
    </main>
    
  </div>
</template>
