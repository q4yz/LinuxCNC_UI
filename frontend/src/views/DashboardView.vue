<script setup>
// Dashboard composition. Module-owned panels are imported statically
// — every module is a hard dependency, and the lazy
// ``defineAsyncComponent`` / ``import.meta.glob(..., { eager: false
// })`` discovery has been removed in favour of eager, direct imports
// (see ``.agent/STATE.md`` § 13 for the no-lazy-imports rule and
// ``frontend/scripts/check-no-lazy-imports.mjs`` for the CI lint).

import { computed, markRaw } from 'vue'
import registry from '../core/modules/registry'

import NgcCoordinateSystemViewer from '../components/NgcCoordinateSystemViewer.vue'
import ConsolePanel from '../components/ConsolePanel.vue'
import DebugPanel from '../components/DebugPanel.vue'
import ActivePrintWidget from '../components/ActivePrintWidget.vue'

// Static imports for every dashboard panel. Module components are
// hard dependencies so removing any of these breaks the build — that
// is the desired behaviour. ``markRaw`` keeps the component
// definitions out of Vue's deep reactivity so they can be safely
// stored in the registry's reactive Map without wrapping them in a
// Proxy (which Vue warns about: "Component that was made a reactive
// object").
import CameraViewerRaw from '../modules/camera/components/CameraViewer.vue'
import TemperaturePanelRaw from '../modules/temperature/components/TemperaturePanel.vue'
import DroPanelRaw from '../modules/machine/components/DroPanel.vue'
import JogControlsRaw from '../modules/machine/components/JogControls.vue'
import ToolPanelRaw from '../modules/tools/components/ToolPanel.vue'
import MacroPanelRaw from '../modules/macros/components/MacroPanel.vue'
import McodePanelRaw from '../modules/macros/components/McodePanel.vue'

const CameraViewer = markRaw(CameraViewerRaw)
const TemperaturePanel = markRaw(TemperaturePanelRaw)
const DroPanel = markRaw(DroPanelRaw)
const JogControls = markRaw(JogControlsRaw)
const ToolPanel = markRaw(ToolPanelRaw)
const MacroPanel = markRaw(MacroPanelRaw)
const McodePanel = markRaw(McodePanelRaw)

// ``registry.modules`` is a reactive Map so ``.has`` is tracked;
// the computed flips once boot completes. Every panel is mounted
// unconditionally; the registry guarantees every module shipped in
// the repo is present.
const cameraMounted = computed(() => registry.modules.has('camera'))
const temperatureMounted = computed(() => registry.modules.has('temperature'))
const machineMounted = computed(() => registry.modules.has('machine'))
const toolsMounted = computed(() => registry.modules.has('tools'))
const macrosMounted = computed(() => registry.modules.has('macros'))
</script>

<template>
  <div class="h-full overflow-y-auto pr-2">
    <!-- Changed from grid to flex flex-wrap -->
    <div class="flex flex-wrap gap-6 pb-8">

      <!-- Left Column: flex-1 tells it to take 1 part space, but NEVER go below 570px -->
      <div class="flex-1 min-w-[min(100%,570px)] flex flex-col space-y-6">

        <DroPanel v-if="machineMounted" />

        <TemperaturePanel v-if="temperatureMounted" />

        <ToolPanel v-if="toolsMounted" />

        <MacroPanel v-if="macrosMounted" />

        <McodePanel v-if="macrosMounted" />

        <JogControls v-if="machineMounted" />
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
            <NgcCoordinateSystemViewer />
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
