<script setup>
// App shell. Vue Router owns the active view; the sidebar uses
// ``router.push`` for navigation and ``useRoute().name`` for
// highlighting the current entry.

import { computed, defineAsyncComponent, shallowRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import registry from './core/modules/registry'
import { useMachineStore } from './stores/machine-compat'
import AppSidebar from './components/AppSidebar.vue'
import EStopHeader from './components/EStopHeader.vue'

// ``useMachineStore`` is supplied by the optional compatibility
// adapter. When the machine module is mounted, the module registers
// its real store before the app mounts; when it is absent, the
// adapter is intentionally inert so the shell can still render
// its placeholders.
const store = useMachineStore()

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

    <!-- Global Emergency Stop header. Sits above the sidebar so the
         safety button stays visible no matter which view is active
         or how far the operator has scrolled. See issue #103. -->
    <EStopHeader />

    <!-- Sidebar + main content row. ``flex-1`` lets this row
         absorb the leftover vertical space below the sticky
         header; ``overflow-hidden`` keeps the sidebar and main
         panes from bleeding into each other. -->
    <div class="flex flex-1 overflow-hidden">

      <!-- Sidebar Navigation: AppSidebar reads the active route
           and calls ``router.push`` itself, so we pass nothing here. -->
      <AppSidebar />

      <!-- Main Content Area: ``<router-view>`` renders the active
           route's component. Module-owned views (registry modules)
           override the slot when their id matches the route name. -->
      <main class="flex-1 overflow-y-auto p-4 lg:p-8">
        <component v-if="moduleView" :is="moduleView" />
        <router-view v-else />
      </main>

    </div>

  </div>
</template>