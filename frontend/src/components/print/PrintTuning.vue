<script setup lang="ts">
// Print tuning on the Job status card while a print runs or is paused:
// the slicer's progress / time left (its M73 lines), the live Z offset
// (babystepping), the flow (M221) and excluding objects. Polls
// ``/api/v1/print-tuning`` every 2 s while mounted.
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { BaseButton } from "../../ui/index.ts";
import BaseInput from "../../ui/BaseInput.vue";
import { useConsoleStore } from "../../stores/console";
import { describeErrorOr } from "../../core/error-format";
import { printTuningFacade, type PrintTuningState } from "../../facades/printTuningFacade";

const POLL_MS = 2000;
const Z_STEPS = [-0.05, -0.01, 0.01, 0.05];

const consoleStore = useConsoleStore();
const state = ref<PrintTuningState | null>(null);
const flowInput = ref<string | number>("");
const busy = ref(false);
let timer: ReturnType<typeof setInterval> | null = null;

async function refresh(): Promise<void> {
  try {
    state.value = await printTuningFacade.get();
    if (flowInput.value === "" && state.value) flowInput.value = state.value.flow;
  } catch {
    // the card shows the last state; the next poll tries again
  }
}

async function run(what: string, action: () => Promise<PrintTuningState>): Promise<void> {
  busy.value = true;
  try {
    state.value = await action();
  } catch (error) {
    consoleStore.error(`${what}: ${describeErrorOr(error)}`);
  } finally {
    busy.value = false;
  }
}

const adjustZ = (delta: number) => run("Z offset", () => printTuningFacade.adjustZ(delta));
const resetZ = () => run("Z offset", () => printTuningFacade.setZ(0));
const applyFlow = () => {
  const percent = Number(flowInput.value);
  if (!Number.isFinite(percent)) return;
  void run("Flow", () => printTuningFacade.setFlow(percent));
};
const toggleObject = (index: number, excluded: boolean) =>
  run("Exclude object", () => printTuningFacade.exclude(index, excluded));

const zLabel = computed(() => {
  const z = state.value?.z_offset ?? 0;
  return `${z >= 0 ? "+" : ""}${z.toFixed(3)} mm`;
});

const slicerRemaining = computed<string | null>(() => {
  const minutes = state.value?.progress?.remaining_min;
  if (minutes === null || minutes === undefined) return null;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
});

onMounted(() => {
  void refresh();
  timer = setInterval(() => void refresh(), POLL_MS);
});
onBeforeUnmount(() => {
  if (timer !== null) clearInterval(timer);
});
</script>

<template>
  <div v-if="state" class="space-y-3 border-t border-gray-700 pt-3 text-sm" data-testid="print-tuning">
    <div
        v-if="state.progress"
        class="flex items-center justify-between text-xs text-gray-400 font-mono"
        data-testid="print-tuning-slicer"
    >
      <span>Slicer</span>
      <span>
        <template v-if="state.progress.percent !== null && state.progress.percent !== undefined">
          {{ state.progress.percent.toFixed(0) }}%
        </template>
        <template v-if="slicerRemaining"> · {{ slicerRemaining }} left</template>
      </span>
    </div>

    <div class="flex flex-wrap items-center gap-2" data-testid="print-tuning-z">
      <span class="w-20 text-xs uppercase tracking-wider text-gray-400">Z offset</span>
      <span class="w-24 font-mono text-gray-200">{{ zLabel }}</span>
      <BaseButton
          v-for="step in Z_STEPS"
          :key="step"
          size="sm"
          variant="secondary"
          :disabled="busy"
          :title="`Move the nozzle ${step > 0 ? 'up' : 'down'} ${Math.abs(step)} mm`"
          @click="adjustZ(step)"
      >{{ step > 0 ? "+" : "−" }}{{ Math.abs(step) }}</BaseButton>
      <BaseButton size="sm" variant="secondary" :disabled="busy || state.z_offset === 0" @click="resetZ">0</BaseButton>
    </div>

    <div class="flex flex-wrap items-center gap-2" data-testid="print-tuning-flow">
      <span class="w-20 text-xs uppercase tracking-wider text-gray-400">Flow</span>
      <BaseInput v-model="flowInput" type="number" class="w-24 text-right text-xs font-mono" @keyup.enter="applyFlow" />
      <span class="text-xs text-gray-400">%</span>
      <BaseButton size="sm" variant="primary" :disabled="busy" @click="applyFlow">Set</BaseButton>
      <span class="text-xs text-gray-500">now {{ state.flow }} %</span>
    </div>

    <div v-if="state.objects?.length" class="space-y-1" data-testid="print-tuning-objects">
      <div class="text-xs uppercase tracking-wider text-gray-400">Objects</div>
      <div
          v-for="object in state.objects"
          :key="object.index"
          class="flex items-center justify-between rounded border border-gray-700 px-2 py-1"
          :class="object.excluded ? 'opacity-60' : ''"
      >
        <span class="truncate font-mono text-xs" :class="object.excluded ? 'line-through text-gray-500' : 'text-gray-200'">
          {{ object.name }}
        </span>
        <BaseButton
            size="sm"
            :variant="object.excluded ? 'secondary' : 'danger'"
            :disabled="busy"
            @click="toggleObject(object.index, !object.excluded)"
        >{{ object.excluded ? "Include" : "Exclude" }}</BaseButton>
      </div>
      <p class="text-[10px] text-gray-500">
        Takes effect for the parts LinuxCNC has not read ahead yet (a few seconds).
      </p>
    </div>
  </div>
</template>
