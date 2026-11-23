<script setup lang="ts">
// The live Z offset (babystepping), flow (M221) and pressure advance of
// the running print — on the Tuning card, under the speed sliders.
import { computed, ref, watch } from "vue";
import { BaseButton } from "../../ui/index.ts";
import BaseInput from "../../ui/BaseInput.vue";
import { usePrintTuning } from "../../composables/usePrintTuning";

/** Babystep sizes (mm): fine for the first layer, coarse to get there. */
const Z_STEPS = [0.01, 0.05, 0.1, 0.25];

const { state, busy, adjustZ, resetZ, setFlow, setPressureAdvance } = usePrintTuning();
const flowInput = ref<string | number>("");
const paInput = ref<string | number>("");

// The inputs start at the machine's values (once known), then are the operator's.
watch(state, (s) => {
  if (!s) return;
  if (flowInput.value === "") flowInput.value = s.flow;
  if (paInput.value === "") paInput.value = s.pressure_advance ?? 0;
}, { immediate: true });

const zLabel = computed(() => {
  const z = state.value?.z_offset ?? 0;
  return `${z >= 0 ? "+" : ""}${z.toFixed(3)} mm`;
});

function applyFlow(): void {
  const percent = Number(flowInput.value);
  if (Number.isFinite(percent)) void setFlow(percent);
}

function applyPressureAdvance(): void {
  const k = Number(paInput.value);
  if (Number.isFinite(k)) void setPressureAdvance(k);
}
</script>

<template>
  <div v-if="state" class="space-y-3 border-t border-gray-700 pt-3 text-sm" data-testid="print-tuning">
    <div class="space-y-2" data-testid="print-tuning-z">
      <div class="flex items-center justify-between">
        <span class="text-sm font-semibold uppercase tracking-wider text-gray-300">Z offset</span>
        <span class="font-mono text-lg font-bold text-blue-400" data-testid="print-tuning-z-value">{{ zLabel }}</span>
      </div>
      <div class="flex flex-wrap items-center gap-1.5">
        <BaseButton
            v-for="step in [...Z_STEPS].reverse()"
            :key="`down-${step}`"
            size="sm"
            variant="secondary"
            :disabled="busy"
            :title="`Move the nozzle down ${step} mm`"
            @click="adjustZ(-step)"
        >−{{ step }}</BaseButton>
        <BaseButton size="sm" variant="secondary" :disabled="busy || state.z_offset === 0" title="Back to 0" @click="resetZ">0</BaseButton>
        <BaseButton
            v-for="step in Z_STEPS"
            :key="`up-${step}`"
            size="sm"
            variant="secondary"
            :disabled="busy"
            :title="`Move the nozzle up ${step} mm`"
            @click="adjustZ(step)"
        >+{{ step }}</BaseButton>
      </div>
    </div>

    <div class="flex flex-wrap items-center gap-2" data-testid="print-tuning-flow">
      <span class="w-14 text-xs uppercase tracking-wider text-gray-400">Flow</span>
      <BaseInput v-model="flowInput" type="number" class="w-20 text-right text-xs font-mono" @keyup.enter="applyFlow" />
      <span class="text-xs text-gray-400">%</span>
      <BaseButton size="sm" variant="primary" :disabled="busy" @click="applyFlow">Set</BaseButton>
      <span class="text-xs text-gray-500">now {{ state.flow }} %</span>
    </div>

    <div class="flex flex-wrap items-center gap-2" data-testid="print-tuning-pa">
      <span class="w-14 text-xs uppercase tracking-wider text-gray-400">PA</span>
      <BaseInput v-model="paInput" type="number" class="w-20 text-right text-xs font-mono" @keyup.enter="applyPressureAdvance" />
      <BaseButton size="sm" variant="primary" :disabled="busy" @click="applyPressureAdvance">Set</BaseButton>
      <span class="text-xs text-gray-500">now {{ state.pressure_advance ?? 0 }}</span>
    </div>
  </div>
</template>
