<script setup>
// Extruder card — heat + motion in one surface. The top half is
// the shared ``HeaterControls`` block (Actual / Target / Set Temp);
// the bottom half is the motion block (Speed input + Retract /
// Extrude + logarithmic distance slider). The motion block owns
// ``EXTRUDER_DISTANCE_OPTIONS`` and the ``distanceFor`` clamp that
// used to live in the panel itself — they were extracted here when
// the per-type markup was split into focused cards.

import { useToolStore } from "../toolStore.js";
import HeaterControls from "./HeaterControls.vue";

const props = defineProps({
  tool: { type: Object, required: true },
});

const toolStore = useToolStore();

// Logarithmic millimetre values for the extruder distance slider.
// Index 0 = 0.1 mm, index 4 = 100 mm.
const EXTRUDER_DISTANCE_OPTIONS = Object.freeze([0.1, 1, 10, 50, 100]);

function distanceFor(tool) {
  // Clamp the index so a stale value cannot throw on access.
  const idx = Math.min(
    Math.max(Number(tool.distance_index) || 0, 0),
    EXTRUDER_DISTANCE_OPTIONS.length - 1,
  );
  return EXTRUDER_DISTANCE_OPTIONS[idx];
}

function handleExtruder(action) {
  toolStore.sendExtruderCommand(
    props.tool.id,
    action,
    distanceFor(props.tool),
    props.tool.set_speed,
  );
}
</script>

<template>
  <div class="space-y-6">
    <HeaterControls :tool="tool" />

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
          @click="handleExtruder('retract')"
        >
          <span class="mr-2">&uarr;</span> Retract
        </button>
        <button
          type="button"
          class="px-6 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded font-semibold shadow transition-colors flex items-center"
          @click="handleExtruder('extrude')"
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
</template>

<style scoped>
/* Hide native number input spinners so the speed input matches the
   dashboard's other controls. */
input[type="number"]::-webkit-inner-spin-button,
input[type="number"]::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
input[type="number"] {
  -moz-appearance: textfield;
}
</style>