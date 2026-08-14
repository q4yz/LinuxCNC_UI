<script setup>
// App shell. Vue Router owns the active view; the sidebar uses
// ``router.push`` for navigation and ``useRoute().name`` for
// highlighting the current entry.

import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import registry from './core/modules/registry'
import { useBaseThreadStore } from './stores/baseThread'
import AppSidebar from './components/AppSidebar.vue'
import ModalConfirmHost from './components/ModalConfirmHost.vue'
import ToastContainer from './components/ToastContainer.vue'
import EStopHeader from './components/EStopHeader.vue'

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

// Resolve the current route to a module's ``mainView``. Modules are
// mandatory: every registry record carries a non-null ``mainView``
// and the contract forbids lazy imports. We look the record up
// synchronously and hand the resolved component straight to the
// template — no ``defineAsyncComponent``, no ``import.meta.glob``.
//
// If the route name does not match a registered module id, we
// return ``null`` so the template falls through to the regular
// ``<router-view>``.
const moduleView = computed(() => {
  const name = route.name
  if (typeof name !== 'string') return null
  const record = registry.modules.get(name)
  return record?.mainView ?? null
})

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