<script setup>
// Tools panel — operator-facing controls for spindles and
// extruders (Issue #64).
//
// The component iterates ``toolStore.tools`` and renders a
// per-type card. The store holds a hard-coded mock tool list
// (one spindle + one extruder) until the dynamic configuration
// implementation lands; the panel is forward-compatible with
// dynamic config because every tool ships its own ``type``.
//
// Reactivity: ``toolStore.tools`` is a Pinia-backed ``ref`` of
// plain objects. Mutating fields in place (``tool.set_speed =``)
// keeps the existing references stable so the input controls
// below don't tear down on every keystroke. We destructure the
// store via the action methods (not state) so the click handlers
// below never need to know the backend URL.

import { useToolStore } from "../toolStore.js";

const toolStore = useToolStore();

// Issue #64 § 3 — the extruder distance slider maps to a fixed
// logarithmic array of millimetre values. Index 0 = 0.1 mm
// (fine tuning), index 4 = 100 mm (long purge). Operators slide
// between indices rather than parsing raw log-space math.
const EXTRUDER_DISTANCE_OPTIONS = Object.freeze([0.1, 1, 10, 50, 100]);

function distanceFor(tool) {
  // Clamp the index so a stale value (e.g. from a future
  // config-driven payload) cannot throw on access.
  const idx = Math.min(
    Math.max(Number(tool.distance_index) || 0, 0),
    EXTRUDER_DISTANCE_OPTIONS.length - 1,
  );
  return EXTRUDER_DISTANCE_OPTIONS[idx];
}

function handleSpindle(tool, action) {
  // The Stop button intentionally passes ``0`` for speed so the
  // backend never has to reason about "is the speed field
  // meaningful for M5?". Forward / Reverse reuse the user's
  // ``set_speed`` input verbatim.
  const speed = action === "stop" ? 0 : tool.set_speed;
  toolStore.sendSpindleCommand(tool.id, action, speed);
}

function handleExtruder(tool, action) {
  toolStore.sendExtruderCommand(
    tool.id,
    action,
    distanceFor(tool),
    tool.set_speed,
  );
}
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden">
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex items-center">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">
        Tools
      </h2>
    </div>

    <div class="p-4 space-y-4 bg-gray-700/20">
      <div
        v-for="tool in toolStore.tools"
        :key="tool.id"
        class="bg-gray-800 border border-gray-700 rounded-lg p-4 shadow-sm"
      >
        <h3 class="text-lg font-semibold text-gray-200 mb-4">{{ tool.name }}</h3>

        <!-- === SPINDLE UI === -->
        <div v-if="tool.type === 'spindle'" class="space-y-4">
          <div class="grid grid-cols-2 gap-4">
            <div class="bg-gray-900 rounded p-3 border border-gray-700">
              <div class="text-xs text-gray-400 uppercase tracking-wider">
                Actual RPM
              </div>
              <div class="text-2xl font-mono text-blue-400">
                {{ tool.actual_rpm }}
              </div>
            </div>
            <div class="bg-gray-900 rounded p-3 border border-gray-700">
              <div class="text-xs text-gray-400 uppercase tracking-wider">
                Target RPM
              </div>
              <div class="text-2xl font-mono text-gray-300">
                {{ tool.target_rpm }}
              </div>
            </div>
          </div>

          <div class="flex items-end gap-4 flex-wrap">
            <div class="flex-1 min-w-[140px]">
              <label class="block text-xs text-gray-400 mb-1">
                Set Speed (RPM)
              </label>
              <input
                v-model.number="tool.set_speed"
                type="number"
                class="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
              >
            </div>
            <button
              type="button"
              class="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded font-semibold transition-colors"
              @click="handleSpindle(tool, 'backward')"
            >
              Reverse
            </button>
            <button
              type="button"
              class="px-4 py-2 bg-red-600 hover:bg-red-500 text-white rounded font-semibold shadow transition-colors"
              @click="handleSpindle(tool, 'stop')"
            >
              Stop
            </button>
            <button
              type="button"
              class="px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded font-semibold shadow transition-colors"
              @click="handleSpindle(tool, 'forward')"
            >
              Forward
            </button>
          </div>
        </div>

        <!-- === EXTRUDER UI === -->
        <div v-else-if="tool.type === 'extruder'" class="space-y-6">
          <div class="flex gap-4 flex-wrap items-end">
            <div class="flex-1 min-w-[140px]">
              <label class="block text-xs text-gray-400 mb-1">
                Speed (mm/min)
              </label>
              <input
                v-model.number="tool.set_speed"
                type="number"
                class="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
              >
            </div>
            <div class="flex items-end gap-2">
              <button
                type="button"
                class="px-6 py-2 bg-gray-700 hover:bg-gray-600 rounded font-semibold transition-colors flex items-center"
                @click="handleExtruder(tool, 'retract')"
              >
                <span class="mr-2">&uarr;</span> Retract
              </button>
              <button
                type="button"
                class="px-6 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded font-semibold shadow transition-colors flex items-center"
                @click="handleExtruder(tool, 'extrude')"
              >
                <span class="mr-2">&darr;</span> Extrude
              </button>
            </div>
          </div>

          <div class="bg-gray-900 p-3 rounded border border-gray-700">
            <div class="flex justify-between text-xs text-gray-400 mb-2">
              <span>Distance (mm)</span>
              <span class="font-mono text-blue-400 font-bold">
                {{ distanceFor(tool) }} mm
              </span>
            </div>
            <input
              v-model.number="tool.distance_index"
              type="range"
              min="0"
              :max="EXTRUDER_DISTANCE_OPTIONS.length - 1"
              step="1"
              class="w-full accent-blue-500"
            >
            <div class="flex justify-between text-xs text-gray-500 mt-2 font-mono px-1">
              <span v-for="val in EXTRUDER_DISTANCE_OPTIONS" :key="val">
                {{ val }}
              </span>
            </div>
          </div>
        </div>

        <div
          v-else
          class="text-sm text-gray-400 italic"
        >
          Unknown tool type: {{ tool.type }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Hide native number input spinners so the speed input matches
   the dashboard's other controls. */
input[type="number"]::-webkit-inner-spin-button,
input[type="number"]::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
input[type="number"] {
  -moz-appearance: textfield;
}
</style>