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
import ActivePrintWidget from '../components/ActivePrintWidget.vue'

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

const CameraViewer     = panelFor('camera',     'CameraViewer')
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
    <!-- Changed from grid to flex flex-wrap -->
    <div class="flex flex-wrap gap-6 pb-8">

      <!-- Left Column: flex-1 tells it to take 1 part space, but NEVER go below 570px -->
      <div class="flex-1 min-w-[min(100%,570px)] flex flex-col space-y-6">

        <DroPanel v-if="machineMounted" />
        <div v-else class="bg-gray-800 rounded-lg p-6 text-gray-500">
          Machine module not mounted.
        </div>

        <TemperaturePanel v-if="temperatureMounted" />

        <JogControls v-if="machineMounted" />
        <div v-else class="bg-gray-800 rounded-lg p-6 text-gray-500">
          Jog controls not mounted.
        </div>
      </div>

      <!-- Right Column: flex-[2] tells it to take twice as much space as the left -->
      <!-- min-w-[600px] ensures the 3D viewer doesn't get crushed -->
      <div class="flex-[2] min-w-[600px] flex flex-col space-y-6">

        <!-- ActivePrintWidget surfaces the current program (or the five
             newest G-code files when idle) and the pause/stop controls,
             so the operator does not have to leave the dashboard while
             a print is running. -->
        <ActivePrintWidget />

        <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden flex flex-col h-[400px] shrink-0">
          <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600">
            <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">Toolpath</h2>
          </div>
          <div class="flex-1 relative">
            <GCodeViewer />
          </div>
        </div>

        <div class="h-[300px]">
          <ConsolePanel />
        </div>

        <div v-if="cameraMounted">
          <CameraViewer />
        </div>

      </div>

    </div>
  </div>
</template>