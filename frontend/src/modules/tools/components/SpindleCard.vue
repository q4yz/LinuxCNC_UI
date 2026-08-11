<script setup>
// Digital spindle card — assumes RPM feedback is available. Renders
// the actual / target RPM tiles plus direction controls (Reverse /
// Stop / Forward). The sibling ``AnalogSpindleCard.vue`` handles
// the feedback-less variant. Tool data shape is sourced from the
// tools store (``toolStore.tools``) and is loaded from the backend
// — there is no hard-coded seed list.

import { useToolStore } from "../toolStore.js";

const props = defineProps({
  tool: { type: Object, required: true },
});

const toolStore = useToolStore();

// Stop passes ``0`` for speed so the backend never has to reason
// about whether the field is meaningful for M5.
function handleSpindle(action) {
  const speed = action === "stop" ? 0 : props.tool.set_speed;
  toolStore.sendSpindleCommand(props.tool.id, action, speed);
}
</script>

<template>
  <div class="space-y-4">
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
          :min="tool.min_rpm ?? undefined"
          :max="tool.max_rpm ?? undefined"
          class="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
        >
        <p
          v-if="tool.min_rpm !== null && tool.min_rpm !== undefined
            || tool.max_rpm !== null && tool.max_rpm !== undefined"
          class="mt-1 text-[11px] text-gray-500 font-mono"
        >
          {{ tool.min_rpm ?? 0 }} – {{ tool.max_rpm ?? "∞" }} RPM
        </p>
      </div>
      <button
        type="button"
        class="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded font-semibold transition-colors"
        @click="handleSpindle('backward')"
      >
        Reverse
      </button>
      <button
        type="button"
        class="px-4 py-2 bg-red-600 hover:bg-red-500 text-white rounded font-semibold shadow transition-colors"
        @click="handleSpindle('stop')"
      >
        Stop
      </button>
      <button
        type="button"
        class="px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded font-semibold shadow transition-colors"
        @click="handleSpindle('forward')"
      >
        Forward
      </button>
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