<script setup>
import { ref, onMounted, computed, defineAsyncComponent, shallowRef } from 'vue'
import registry from './core/modules/registry'
import { useMachineStore } from './stores/machine-compat'
import AppSidebar from './components/AppSidebar.vue'
import DashboardView from './views/DashboardView.vue'
import FilesView from './views/FilesView.vue'
import ConfigView from './views/ConfigView.vue'
import SettingsView from './views/SettingsView.vue'
import ConfigEditor from './components/ConfigEditor.vue'

// ``useMachineStore`` is supplied by the optional compatibility adapter.
// When the machine module is mounted, the module registers its real
// store before the app mounts; when it is absent, the adapter is
// intentionally inert so the shell can still render its placeholders.
const store = useMachineStore()
const currentView = ref('dashboard')
const editorFile = ref(null)
const editorReadOnly = ref(false)
const editorMode = ref('config')
const editorContent = ref('')

// Module-driven sidebar entries route to a module-owned view when
// the entry's id matches a mounted module's manifest id. ``eager:
// false`` keeps the glob lazy (see ``.agent/STATE.md`` § 1);
// ``shallowRef`` avoids deep reactivity churn when the async loader
// returns a new function identity per render.
const moduleViewImports = import.meta.glob(
  './modules/*/components/*.vue',
  { eager: false },
)

const moduleViewCache = shallowRef(new Map())

function loadModuleView(moduleId) {
  const target = Object.keys(moduleViewImports).find(
    (p) =>
      p.includes(`/${moduleId}/components/`) &&
      !/Settings(?:Panel)?\.vue$/.test(p),
  )
  if (!target) return null
  const cached = moduleViewCache.value.get(moduleId)
  if (cached) return cached
  const loader = moduleViewImports[target]
  const asyncComp = defineAsyncComponent(async () => {
    const mod = await loader()
    return mod.default ?? mod
  })
  moduleViewCache.value.set(moduleId, asyncComp)
  return asyncComp
}

const moduleView = computed(() => {
  // Returns ``null`` for built-in views so the template falls
  // through to the hard-coded branches.
  if (registry.modules.has(currentView.value)) {
    return loadModuleView(currentView.value)
  }
  return null
})

onMounted(() => {
  // The registry is booted before mount. Keep this guarded fallback for
  // deployments that explicitly exclude the machine module.
  if (!registry.modules.has('machine')) {
    store.connect()
  }
})

// Exposed so child views can trigger the full-screen editor
function openEditor(filename, readOnly = false, mode = 'config', content = '') {
  editorFile.value = filename
  editorReadOnly.value = readOnly
  editorMode.value = mode
  editorContent.value = content
}

async function handleEditorSave(newContent) {
  if (editorMode.value === 'profile') {
    const configStore = useMachineConfigStore()
    // Trigger your store's save action (adjust the method name if yours is different)
    await configStore.saveProfile(editorFile.value, newContent)
  }
}

</script>

<template>
  <ConfigEditor
    v-if="editorFile"
    key="fullscreen-editor"
    :filename="editorFile"
    :read-only="editorReadOnly"
    :mode="editorMode"
    v-model="editorContent"
    @close="editorFile = null"
    @save="handleEditorSave"
  />
  <div v-else key="main-layout" class="flex h-screen overflow-hidden bg-gray-900 text-white font-sans">

    <!-- Sidebar Navigation -->
    <AppSidebar :currentView="currentView" @navigate="(view) => currentView = view" />

    <!-- Main Content Area -->
    <main class="flex-1 overflow-y-auto p-4 lg:p-8">
      <!-- Module-owned views win over the hard-coded branches. -->
      <component v-if="moduleView" :is="moduleView" @edit="openEditor" />
      <DashboardView v-else-if="currentView === 'dashboard'" />
      <FilesView v-else-if="currentView === 'files'" @edit="openEditor" />

      <!-- Catch the edit event from the ConfigView panels -->
      <ConfigView v-else-if="currentView === 'config'" @edit="openEditor" />

      <SettingsView v-else-if="currentView === 'settings'" />
    </main>

  </div>
</template>