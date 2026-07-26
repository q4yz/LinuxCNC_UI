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
// When the machine module is mounted, the module registers its real store
// before the app mounts; when it is absent, the adapter is intentionally
// inert so the shell can still render its placeholders.
const store = useMachineStore()
const currentView = ref('dashboard')
const editorFile = ref(null)
const editorReadOnly = ref(false)

// Module-driven sidebar entries route to a module-owned view when
// the entry's id matches a mounted module's manifest id. The glob
// resolves to ``frontend/src/modules/<id>/components/<Name>.vue``
// where ``Name`` is the default export from the module's view shell.
// The machineconfig module no longer ships its own shell because the
// updated panels now live directly inside the legacy ``ConfigView``.
//
// ``eager: false`` keeps the glob lazy so a module excluded by the
// ``MODULES_ENABLED`` whitelist never appears in the bundle (Gotcha
// #1). ``shallowRef`` avoids deep reactivity churn when the async
// loader returns a new function identity per render.
const moduleViewImports = import.meta.glob(
  './modules/*/components/*.vue',
  { eager: false },
)

const moduleViewCache = shallowRef(new Map())

function loadModuleView(moduleId) {
  const target = Object.keys(moduleViewImports).find(
    (p) => p.includes(`/${moduleId}/components/`),
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
  // Resolve the active view lazily — once a module's id matches the
  // current nav selection, look up its main view component. Returns
  // ``null`` for built-in views (dashboard / files / config /
  // settings) so the template falls through to the hard-coded
  // branches.
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
       <!-- Module-owned views win over the hard-coded branches. The
         machineconfig module now reuses the legacy ConfigView slot,
         so its sidebar entry is mapped to ``config`` instead of a
         standalone module shell. -->
      <component v-if="moduleView" :is="moduleView" />
      <DashboardView v-else-if="currentView === 'dashboard'" />
      <FilesView v-else-if="currentView === 'files'" />
      <ConfigView v-else-if="currentView === 'config'" />
      <SettingsView v-else-if="currentView === 'settings'" />
    </main>

  </div>
</template>