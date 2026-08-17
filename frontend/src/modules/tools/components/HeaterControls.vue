<script setup>
// Heater controls — Actual Temp + Target Temp tiles, a clamped
// Set Temp input, and a Set / Off pair. Shared between
// ``HeatedBedCard`` (heat-only tool) and ``ExtruderCard`` (heat +
// motion). The tool object's ``min_temp`` / ``max_temp`` drive the
// input's clamp and the muted range helper text.
//
// ``target`` is read from the tool object if present (the backend
// pushes the latest target via telemetry); the input is a local
// working value so the operator can type without immediately
// dispatching.

import { ref } from "vue";

import { useToolStore } from "../toolStore";

const props = defineProps({
  tool: { type: Object, required: true },
});

const toolStore = useToolStore();

// Local working value for the input. Seeded from the tool's
// persisted ``set_temp`` (or current ``target``) on mount; cleared
// by ``Off`` so the operator can re-enter a value without first
// clearing it.
const inputTemp = ref(
  typeof props.tool.set_temp === "number"
    ? props.tool.set_temp
    : typeof props.tool.target === "number"
      ? props.tool.target
      : 0,
);

function hasRange() {
  return (
    (props.tool.min_temp !== null && props.tool.min_temp !== undefined) ||
    (props.tool.max_temp !== null && props.tool.max_temp !== undefined)
  );
}

function rangeLabel() {
  const lo = props.tool.min_temp ?? 0;
  const hi = props.tool.max_temp ?? "∞";
  return `${lo} – ${hi} °C`;
}

async function applyTemp() {
  const t = Number(inputTemp.value || 0);
  await toolStore.sendToolTarget(props.tool.id, t);
  if (typeof props.tool.target === "number") {
    props.tool.target = t;
  }
}

async function turnOff() {
  inputTemp.value = 0;
  await toolStore.sendToolTarget(props.tool.id, 0);
  if (typeof props.tool.target === "number") {
    props.tool.target = 0;
  }
}
</script>

<template>
  <div class="space-y-4">
    <div class="grid grid-cols-2 gap-4">
      <div class="bg-gray-900 rounded p-3 border border-gray-700">
        <div class="text-xs text-gray-400 uppercase tracking-wider">
          Actual Temp
        </div>
        <div class="text-2xl font-mono text-blue-400">
          {{ tool.actual ?? "—" }}
        </div>
      </div>
      <div class="bg-gray-900 rounded p-3 border border-gray-700">
        <div class="text-xs text-gray-400 uppercase tracking-wider">
          Target Temp
        </div>
        <div class="text-2xl font-mono text-gray-300">
          {{ tool.target ?? "—" }}
        </div>
      </div>
    </div>

    <div class="flex items-end gap-4 flex-wrap">
      <div class="flex-1 min-w-[140px]">
        <label class="block text-xs text-gray-400 mb-1">
          Set Temp (°C)
        </label>
        <input
          v-model.number="inputTemp"
          type="number"
          :min="tool.min_temp ?? undefined"
          :max="tool.max_temp ?? undefined"
          class="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
          @keyup.enter="applyTemp"
        >
        <p
          v-if="hasRange()"
          class="mt-1 text-[11px] text-gray-500 font-mono"
        >
          {{ rangeLabel() }}
        </p>
      </div>
      <button
        type="button"
        class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded font-semibold shadow transition-colors"
        @click="applyTemp"
      >
        Set
      </button>
      <button
        type="button"
        class="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded font-semibold transition-colors"
        @click="turnOff"
      >
        Off
      </button>
    </div>
  </div>
</template>

<style scoped>
/* Hide native number input spinners so the temp input matches the
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