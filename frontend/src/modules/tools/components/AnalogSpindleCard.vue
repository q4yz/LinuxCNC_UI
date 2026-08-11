<script setup>
// Analog spindle card — the spindle has no RPM feedback (typical
// of a VFD driven by a 0–10 V analogue signal), so the actual /
// target RPM tiles and the digital-spindle direction buttons are
// hidden. Only the commanded speed and an Enable / Disable pair
// remain. Reuses ``sendSpindleCommand`` with the existing actions
// (``forward`` ⇒ enable with ``set_speed``, ``stop`` ⇒ disable at 0)
// so no new store action is needed.

import { useToolStore } from "../toolStore.js";

const props = defineProps({
  tool: { type: Object, required: true },
});

const toolStore = useToolStore();

// Same speed contract as the digital card — Disable passes ``0``,
// Enable passes the operator-set RPM. The backend decides how to
// map that onto the analogue output.
function handleSpindle(action) {
  const speed = action === "stop" ? 0 : props.tool.set_speed;
  toolStore.sendSpindleCommand(props.tool.id, action, speed);
}
</script>

<template>
  <div class="space-y-4">
    <p class="text-xs text-gray-400 italic">
      Analog spindle — no RPM feedback. Set a speed and enable the output.
    </p>

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
        class="px-4 py-2 bg-red-600 hover:bg-red-500 text-white rounded font-semibold shadow transition-colors"
        @click="handleSpindle('stop')"
      >
        Disable
      </button>
      <button
        type="button"
        class="px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded font-semibold shadow transition-colors"
        @click="handleSpindle('forward')"
      >
        Enable
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