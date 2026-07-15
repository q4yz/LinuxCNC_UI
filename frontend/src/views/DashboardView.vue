<script setup>
// Dashboard composition. Module-owned panels (``camera``,
// ``temperature``, ``machine``) are loaded via
// ``defineAsyncComponent`` resolved at runtime through
// ``import.meta.glob`` so removing any single
// ``frontend/src/modules/<id>/`` folder leaves the build intact
// (MODULE_SYSTEM_ROADMAP.md § 12 Gotcha #1).
//
// The unmigrated panels (``GCodeViewer``/``ConsolePanel``/
// ``DebugPanel``) keep static imports for now; they will convert
// to async when those features migrate.
//
// Reactivity: ``registry.modules`` is a Vue-reactive Map (see
// ``frontend/src/core/modules/registry.js``), so the ``computed``s
// below re-evaluate the moment the registry flips a module into
// its mounted set after boot completes.

import { computed, defineAsyncComponent } from 'vue'
import registry from '../core/modules/registry'

import GCodeViewer from '../components/GCodeViewer.vue'
import ConsolePanel from '../components/ConsolePanel.vue'
import DebugPanel from '../components/DebugPanel.vue'

// ``import.meta.glob`` with ``eager: false`` records dynamic-import
// functions keyed by file path; the dashboard keeps building with
// an empty ``modules/`` folder because Vite doesn't try to resolve
// the paths at build time.
const modulePanelImports = import.meta.glob(
  '../modules/*/components/*.vue',
  { eager: false },
)

/**
 * Resolve a module panel by id at component-creation time.
 * Returns ``null`` when the module folder has been deleted, which
 * the dashboard ``v-if`` gate ignores as "do not render" — this is
 * the nullable-module guarantee from Gotcha #1.
 */
function panelFor(folder, name) {
  return defineAsyncComponent(async () => {
    const target = Object.keys(modulePanelImports).find(
      (p) => p.includes(`/${folder}/`) && p.endsWith(`/${name}.vue`),
    )
    if (!target) return null
    const mod = await modulePanelImports[target]()
    return mod.default ?? mod
  })
}

const CameraPanel      = panelFor('camera',     'CameraPanel')
const TemperaturePanel = panelFor('temperature', 'TemperaturePanel')
// Machine panels are loaded the same way as camera / temperature.
// When the folder has been deleted, the ``panelFor`` helper returns
// ``null`` and the ``v-if`` falls through to the placeholder card
// so the dashboard layout stays consistent (Gotcha #1).
const DroPanel         = panelFor('machine',    'DroPanel')
const JogControls      = panelFor('machine',    'JogControls')

// Mounted? ``registry.modules`` is a reactive Map (see
// ``registry.js``) so ``.has`` is tracked; the computed flips
// once the registry boots and mounts the module.
const cameraMounted      = computed(() => registry.modules.has('camera'))
const temperatureMounted = computed(() => registry.modules.has('temperature'))
const machineMounted     = computed(() => registry.modules.has('machine'))
</script>

<template>
  <div class="h-full overflow-y-auto pr-2">
    <!-- Grid Layout for Panels -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 pb-8">

      <!-- Left Column: DRO, Heater & Controls -->
      <div class="col-span-1 flex flex-col space-y-6">
        <!-- DRO slot: rendered when the machine module folder is on
             disk AND the registry reports the module mounted.
             Otherwise the slot shows the "Machine module not
             mounted." placeholder so the layout stays consistent. -->
        <DroPanel v-if="machineMounted" />
        <div
          v-else
          class="bg-gray-800 rounded-lg p-6 text-gray-500"
        >
          Machine module not mounted.
        </div>

        <!-- Temperature panel: only rendered when the module folder
             is on disk AND the registry reports the module mounted
             (Gotcha #1). When the folder has been deleted, the slot
             is left empty so the dashboard still lays out cleanly. -->
        <TemperaturePanel v-if="temperatureMounted" />

        <!-- Jog controls slot: same nullable-module pattern as the
             DRO. -->
        <JogControls v-if="machineMounted" />
        <div
          v-else
          class="bg-gray-800 rounded-lg p-6 text-gray-500"
        >
          Jog controls not mounted.
        </div>
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
