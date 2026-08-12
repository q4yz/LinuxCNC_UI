<script setup>
// App shell. Vue Router owns the active view; the sidebar uses
// ``router.push`` for navigation and ``useRoute().name`` for
// highlighting the current entry.

import { computed, defineAsyncComponent, markRaw, shallowRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import registry from './core/modules/registry'
import { useMachineStore } from './stores/machine-compat'
import { useBaseThreadStore } from './stores/baseThread'
import AppSidebar from './components/AppSidebar.vue'
import ModalConfirmHost from './components/ModalConfirmHost.vue'
import ToastContainer from './components/ToastContainer.vue'
import EStopHeader from './components/EStopHeader.vue'

// ``useMachineStore`` is supplied by the optional compatibility
// adapter. When the machine module is mounted, the module registers
// its real store before the app mounts; when it is absent, the
// adapter is intentionally inert so the shell can still render
// its placeholders.
const store = useMachineStore()

// The base-thread store is the dashboard's "slow channel" — one
// 1 Hz REST round-trip that bundles every slow stream (program
// progress, temperature sensors, tool list) into one payload. We
// boot it at app mount rather than from any specific panel so a
// view mounted later (e.g. the dashboard's ActivePrintWidget) gets
// populated data on its first frame instead of waiting a second
// for the first poll to land. The poll is cheap enough (one HTTP
// request per second) to keep running for the entire session.
useBaseThreadStore().start()

const route = useRoute()
const router = useRouter()

// Map module ids to their lazily-loaded main view component. Kept
// in a Vue Router-free computed so registry views can be rendered
// inline at the current route's component slot.
const moduleViewImports = import.meta.glob(
  './modules/*/components/*.vue',
  { eager: false },
)

const moduleViewCache = shallowRef(new Map())

function loadModuleView(moduleId) {
  // Prefer the explicit ``mainView`` on the registry record. Modules
  // migrated to the new contract set this themselves; App.vue no
  // longer depends on file-naming heuristics.
  const record = registry.modules.get(moduleId)
  if (record?.mainView) {
    return record.mainView
  }
  // Legacy fallback: alphabetical first ``components/*.vue`` file
  // excluding the Settings panel. Kept so unconverted modules still
  // load during the migration window — see ``protocols.js`` for the
  // recommended path.
  const target = Object.keys(moduleViewImports).find(
    (p) =>
      p.includes(`/${moduleId}/components/`) &&
      !/Settings(?:Panel)?\.vue$/.test(p),
  )
  if (!target) return null
  const cached = moduleViewCache.value.get(moduleId)
  if (cached) return cached
  const loader = moduleViewImports[target]
  // ``markRaw`` prevents Vue's deep reactivity from wrapping the
  // AsyncComponentWrapper in a Proxy. The ``<component :is=...>``
  // binding downstream expects a raw component definition; without
  // ``markRaw`` Vue logs "Component that was made a reactive
  // object" and burns CPU on every route change.
  const asyncComp = markRaw(defineAsyncComponent(async () => {
    const mod = await loader()
    return mod.default ?? mod
  }))
  moduleViewCache.value.set(moduleId, asyncComp)
  return asyncComp
}

// If the current route name matches a mounted module id, render
// that module's main view in place of the route component. This
// preserves the registry-based module-owns-view contract while
// living inside the router-managed ``<router-view>``.
const moduleView = computed(() => {
  const name = route.name
  if (typeof name === 'string' && registry.modules.has(name)) {
    return loadModuleView(name)
  }
  return null
})

// Connect the machine store on first mount if the module is not
// registered (the real machine module wires this up itself).
if (!registry.modules.has('machine')) {
  store.connect()
}

// Sidebar navigates via Vue Router. Keeping this thin keeps the
// router authoritative for the active URL.
function navigate(view) {
  router.push({ name: view })
}
</script>

<template>
  <div class="flex flex-col h-screen overflow-hidden bg-gray-900 text-white font-sans">

    <!-- Global Emergency Stop header. -->
    <EStopHeader />

    <!-- Sidebar + main content row. -->
    <div class="flex flex-1 overflow-hidden">

      <!-- Sidebar Navigation -->
      <AppSidebar />

      <!-- Main Content Area -->
      <main class="flex-1 overflow-y-auto p-4 lg:p-8">
        <component v-if="moduleView" :is="moduleView" />
        <router-view v-else />
      </main>

    </div>

    <!-- Global Overlays -->
    <ModalConfirmHost />
    <ToastContainer />

  </div>
</template>