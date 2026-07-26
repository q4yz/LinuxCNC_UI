<script setup>
import { ref, onMounted, computed, defineAsyncComponent, shallowRef } from 'vue'
import registry from './core/modules/registry'
import { useMachineStore } from './stores/machine'
import AppSidebar from './components/AppSidebar.vue'
import DashboardView from './views/DashboardView.vue'
import FilesView from './views/FilesView.vue'
import ConfigView from './views/ConfigView.vue'
import SettingsView from './views/SettingsView.vue'
import ConfigEditor from './components/ConfigEditor.vue'

// ``useMachineStore`` returns the module-scoped store via the legacy
// shim (``frontend/src/stores/machine.js``). The store's ``connect``
// is idempotent, so calling it here is safe even when the machine
// module's ``onLoad`` hook already opened a WebSocket — the guard in
// ``connect()`` no-ops if ``connectionStatus`` is already
// ``'connected'`` or ``'connecting'``.
//
// As of issue #38 we keep this call as a fallback for deployments
// that exclude the machine module via ``MODULES_ENABLED`` so the
// legacy telemetry path stays alive. The machine module's own
// ``onLoad`` / ``onUnload`` hooks wire / tear down the same socket
// when the module **is** mounted, so this line is a no-op in the
// default case.
const store = useMachineStore()
const currentView = ref('dashboard')
const editorFile = ref(null)
const editorReadOnly = ref(false)

// Module-driven sidebar entries route to a module-owned view when
// the entry's id matches a mounted module's manifest id. The glob
// resolves to ``frontend/src/modules/<id>/components/<Name>.vue``
// where ``Name`` is the default export from the module's
// ``index.js`` ``components`` map (``MainView`` for issue #41).
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
  // Connect only when the machine module has not already wired the
  // WebSocket via ``onLoad``. ``registry.modules`` is a reactive Map
  // (see ``frontend/src/core/modules/registry.js``) — by the time
  // this fires, the registry has typically booted, but we re-check
  // defensively against the rare race where the registry is still
  // mid-boot.
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
      <!-- Module-owned views win over the hard-coded branches so a
           module with sidebar id "machineconfig" gets its own
           MachineConfigView rather than the legacy ConfigView. -->
      <component v-if="moduleView" :is="moduleView" />
      <DashboardView v-else-if="currentView === 'dashboard'" />
      <FilesView v-else-if="currentView === 'files'" />
      <ConfigView v-else-if="currentView === 'config'" />
      <SettingsView v-else-if="currentView === 'settings'" />
    </main>

  </div>
</template>