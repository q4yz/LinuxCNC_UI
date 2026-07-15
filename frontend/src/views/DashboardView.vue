<script setup>
// Dashboard composition. Each module-owned panel is loaded via
// ``defineAsyncComponent`` so removing the corresponding
// ``frontend/src/modules/<id>/`` folder leaves the build intact
// (MODULE_SYSTEM_ROADMAP.md § 12 Gotcha #1).
//
// The dashboard then reads ``registry.modules`` to decide whether to
// render the panel at all. The legacy static imports were dropped
// because they would re-introduce the very "deleting a folder breaks
// the build" failure mode the module system is designed to avoid.
import { defineAsyncComponent, computed } from 'vue'
import registry from '../core/modules/registry'
// This view acts as a wrapper containing the main UI grid components.
// Panels that have been migrated into the module system are loaded
// via ``import.meta.glob`` so removing a module folder does not
// break the build (Gotcha #1: lazy imports). Panels that have not
// yet been migrated are imported statically below.
//
// Migration status:
//   * TemperaturePanel → ``frontend/src/modules/temperature``
//     (issue #32).
//   * CameraPanel, DroPanel, JogControls, GCodeViewer, ConsolePanel,
//     DebugPanel — not yet migrated; static imports kept.

import { computed, defineAsyncComponent, shallowRef } from 'vue'
import DroPanel from '../components/DroPanel.vue'
import JogControls from '../components/JogControls.vue'
import GCodeViewer from '../components/GCodeViewer.vue'
import ConsolePanel from '../components/ConsolePanel.vue'
import DebugPanel from '../components/DebugPanel.vue'
import CameraPanel from '../components/CameraPanel.vue'

import { registry } from '../core/modules/registry'

// ``import.meta.glob`` with ``eager: false`` builds a record of
// dynamic-import functions keyed by file path. Vite does not
// resolve these at build time when ``eager: false`` is set, so
// the dashboard keeps building even when a module folder is
// deleted (Gotcha #1). When the folder is present, the dashboard
// can lazy-import the component on demand.
//
// The glob is rooted at ``./modules/`` and matches the
// ``components/<PascalName>.vue`` convention used by every module.
const moduleComponentImports = import.meta.glob(
  '../modules/*/components/*.vue',
  { eager: false },
)

// ``registry.modules`` is the canonical source of truth for which
// modules have been mounted at runtime. We use it as the gate so
// the dashboard renders an empty slot when the module folder has
// been deleted — this is the nullable-module guarantee from
// MODULE_SYSTEM_ROADMAP.md § 12 Gotcha #1.
const temperatureMounted = computed(() => registry.modules.has('temperature'))

// Resolve the temperature component only when the module is
// mounted AND the glob found a matching file (i.e. the folder
// hasn't been deleted). ``shallowRef`` keeps Vue from recursively
// observing the component definition, which would be wasteful for
// a static component object.
const AsyncTemperaturePanel = shallowRef(null)
temperatureMounted.value && resolveTemperature()

async function resolveTemperature() {
  if (!temperatureMounted.value) {
    AsyncTemperaturePanel.value = null
    return
  }
  // Find the glob entry for the temperature panel. The path looks
  // like ``../modules/temperature/components/TemperaturePanel.vue``.
  const target = Object.keys(moduleComponentImports).find((p) =>
    /\/modules\/temperature\/components\/TemperaturePanel\.vue$/.test(p),
  )
  if (!target) {
    AsyncTemperaturePanel.value = null
    return
  }
  const loader = moduleComponentImports[target]
  AsyncTemperaturePanel.value = defineAsyncComponent(loader)
}

// Re-resolve when the registry flips mounted/unmounted (e.g. after
// a hot reload deletes the folder).
import { watch } from 'vue'
watch(temperatureMounted, () => resolveTemperature())

// Lazy camera panel. The ``() => import(...)`` callback is only
// evaluated if the dashboard actually renders ``<CameraPanel />``,
// which only happens when the module is mounted.
const CameraPanel = defineAsyncComponent(
  () => import('../modules/camera/components/CameraPanel.vue'),
)

// Track whether each module is currently mounted so the dashboard
// can render placeholder slots in their place when missing. Today
// only the camera uses this — but having the pattern in place means
// the temperature migration can adopt the same shape without
// re-litigating the layout.
const cameraMounted = computed(() => registry.modules.has('camera'))
</script>

<template>
  <div class="h-full overflow-y-auto pr-2">
    <!-- Grid Layout for Panels -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 pb-8">

      <!-- Left Column: DRO, Heater & Controls -->
      <div class="col-span-1 flex flex-col space-y-6">
        <DroPanel />
        <!-- Temperature panel: only rendered when the module folder
             is on disk AND the registry reports the module mounted
             (Gotcha #1). When the folder has been deleted, the slot
             is left empty so the dashboard still lays out cleanly. -->
        <component :is="AsyncTemperaturePanel" v-if="AsyncTemperaturePanel" />
        <JogControls />
      </div>

      <!-- Right Column: 3D Viewer & Console -->
      <div class="lg:col-span-2 flex flex-col space-y-6">

        <!-- 3D Viewer -->
        <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden flex flex-col h-[400px] shrink-0">
          <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600">
            <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">Toolpath</h2>
          </div>
          <div class="flex-1 relative">
            <GCodeViewer />
          </div>
        </div>

        <!-- Terminal / Console -->
        <div class="h-[300px]">
          <ConsolePanel />

        </div>

        <!--
          Camera slot: rendered only when the camera module is mounted.
          ``v-if`` + ``CameraPanel`` as an async component keeps the
          camera bundle out of the initial chunk (Gotcha #1) and lets
          us delete ``frontend/src/modules/camera/`` cleanly.
        -->
        <div v-if="cameraMounted" class="lg:col-span-2">
          <CameraPanel />
        </div>


      </div>

    </div>
  </div>
</template>