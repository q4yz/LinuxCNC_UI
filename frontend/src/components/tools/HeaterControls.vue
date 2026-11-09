<script setup lang="ts">
// Heater controls — shared by ``HeatedBedCard`` and ``ExtruderCard``.
// Reads the typed ``HeaterState`` from the base-thread snapshot
// (``actualCelsius`` / ``targetCelsius`` / ``minTemp`` / ``maxTemp``).
// The set-point input is a local working value: the snapshot replaces
// the entity every second, so binding to it would wipe what is typed.

import { computed, ref, watch } from "vue";

import type { HeaterState } from "../../entities/tools/Heater";
import { useToolStore } from "../../stores/toolsStore";
import { BaseButton } from "../../ui/index.ts";
import BaseInput from "../../ui/BaseInput.vue";
import {
  clampTarget,
  fillFraction,
  formatCelsius,
  heaterStatus,
  targetFraction,
} from "./heaterView";

const props = defineProps<{
  /** Tool id the set point is sent to. */
  toolId: string;
  heater: HeaterState | null;
}>();

const toolStore = useToolStore();

const inputTemp = ref<number>(props.heater?.targetCelsius ?? 0);
// A new tool selected: start from its target.
watch(() => props.toolId, () => {
  inputTemp.value = props.heater?.targetCelsius ?? 0;
});

const status = computed(() => heaterStatus(props.heater));
const STATUS_LABEL = { off: "Off", heating: "Heating", cooling: "Cooling", "at-temp": "At temp" } as const;
const STATUS_CLASS = {
  off: "bg-gray-800 text-gray-400 border-gray-700",
  heating: "bg-orange-500/15 text-orange-300 border-orange-500/40",
  cooling: "bg-sky-500/15 text-sky-300 border-sky-500/40",
  "at-temp": "bg-green-500/15 text-green-300 border-green-500/40",
} as const;

const fill = computed(() => fillFraction(props.heater) * 100);
const marker = computed(() => {
  const f = targetFraction(props.heater);
  return f === null ? null : f * 100;
});

async function applyTemp() {
  const t = clampTarget(inputTemp.value, props.heater);
  inputTemp.value = t;
  await toolStore.sendToolTarget(props.toolId, t);
}

async function turnOff() {
  inputTemp.value = 0;
  await toolStore.sendToolTarget(props.toolId, 0);
}
</script>

<template>
  <div v-if="heater" class="space-y-3" data-testid="heater-controls">
    <div class="flex items-baseline justify-between gap-3">
      <div class="font-mono">
        <span class="text-3xl text-blue-300" data-testid="heater-actual">{{ formatCelsius(heater.actualCelsius) }}</span>
        <span class="text-lg text-gray-500"> / </span>
        <span class="text-lg text-gray-300" data-testid="heater-target">
          {{ heater.targetCelsius > 0 ? formatCelsius(heater.targetCelsius) : "off" }}
        </span>
        <span class="text-sm text-gray-500"> °C</span>
      </div>
      <span
        class="px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider rounded border"
        :class="STATUS_CLASS[status]"
      >{{ STATUS_LABEL[status] }}</span>
    </div>

    <div class="relative h-2 rounded bg-gray-800 overflow-hidden" :title="`${heater.minTemp} – ${heater.maxTemp} °C`">
      <div
        class="absolute inset-y-0 left-0 transition-all duration-500"
        :class="status === 'at-temp' ? 'bg-green-500' : status === 'off' ? 'bg-gray-500' : 'bg-orange-500'"
        :style="{ width: `${fill}%` }"
      />
      <div v-if="marker !== null" class="absolute inset-y-0 w-0.5 bg-white/80" :style="{ left: `${marker}%` }" />
    </div>
    <div class="flex justify-between text-[11px] text-gray-500 font-mono -mt-1">
      <span>{{ heater.minTemp }}</span>
      <span>{{ heater.maxTemp }} °C</span>
    </div>

    <div class="flex items-center gap-2">
      <BaseInput
        v-model.number="inputTemp"
        type="number"
        :min="heater.minTemp"
        :max="heater.maxTemp"
        class="flex-1 min-w-0"
        aria-label="Set temperature (°C)"
        placeholder="°C"
        @keyup.enter="applyTemp"
      />
      <BaseButton variant="primary" @click="applyTemp">Set</BaseButton>
      <BaseButton variant="secondary" :disabled="heater.targetCelsius <= 0" @click="turnOff">Off</BaseButton>
    </div>
  </div>
  <div v-else class="text-sm text-gray-400 italic">This tool has no heater.</div>
</template>

<style scoped>
:deep(input[type="number"]::-webkit-inner-spin-button),
:deep(input[type="number"]::-webkit-outer-spin-button) {
  -webkit-appearance: none;
  margin: 0;
}
:deep(input[type="number"]) {
  -moz-appearance: textfield;
}
</style>
