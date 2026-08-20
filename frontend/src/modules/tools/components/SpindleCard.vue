<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { storeToRefs } from "pinia";

import { useToolStore } from "../toolStore";
import { SpindleDigital } from "../../../entities/tools";
import { SystemState, useMachineStore } from "../../../stores/stateFacade";

const props = defineProps<{
  tool: SpindleDigital;
}>();

const toolStore = useToolStore();

// Read the machine's current state from the canonical facade store
// (sibling widgets such as ActivePrintWidget / EStopHeader follow
// the same pattern; the parent does not have to thread it through).
const { systemState } = storeToRefs(useMachineStore());

// Local working state
const speedPercentage = ref<number>(100);
const masterOverride = ref<boolean>(false);
const masterOverrideSpeed = ref<number>(props.tool.minRpm ?? 0);

type SpindleRunningState = "idle" | "forward" | "backward" | "stop";

const runningState = ref<SpindleRunningState>("idle");
let postTimer: ReturnType<typeof setTimeout> | null = null;

// --- State Logic ---

// Disabled: Machine is off, estopped, offline, or updating.
const isDisabled = computed(() => {
  return [
    SystemState.OFFLINE,
    SystemState.POWER_OFF,
    SystemState.ESTOP,
    SystemState.UPDATING
  ].includes(systemState.value);
});

// Manual Only: Machine is idle, loaded, or in failure.
// We hide the percentage slider and force Master Override (Manual Control) on.
const isManualOnly = computed(() => {
  return [
    SystemState.IDLE,
    SystemState.LOADED,
    SystemState.FAILURE
  ].includes(systemState.value);
});

// The effective master override state (forced to true if in Manual Only mode)
const isEffectiveMasterOverride = computed(() => isManualOnly.value || masterOverride.value);

// --- RPM Logic ---

const minRpm = computed(() => props.tool.minRpm ?? 0);
const maxRpm = computed(() => props.tool.maxRpm ?? 24000);
const actualRpm = computed(() => props.tool.actualRpm ?? 0);

const minPercent = computed(() => {
  if (!maxRpm.value) return 0;
  return (minRpm.value / maxRpm.value) * 100;
});

const gaugeGradient = computed(() => {
  return {
    background: `linear-gradient(to top,
      #ef4444 0%, #ef4444 ${minPercent.value}%,
      #f97316 ${minPercent.value}%, #f97316 80%,
      #22c55e 80%, #22c55e 100%)`
  };
});

const gaugeCoverHeight = computed(() => {
  if (!maxRpm.value) return '100%';
  const pct = Math.min(100, Math.max(0, (actualRpm.value / maxRpm.value) * 100));
  return `${100 - pct}%`;
});

// --- Actions ---

function handleSpindle(action: SpindleRunningState) {
  if (isDisabled.value) return; // Guard against disabled state

  if (action === "stop") {
    runningState.value = "idle";
    toolStore.sendSpindleCommand(
        props.tool.id,
        "stop",
        0,
        masterOverrideSpeed.value,
        false,
        1.0,
    );
    return;
  }

  // Determine the speed based on effective override mode
  let speedToSet = props.tool.actualRpm ?? 0;

  if (isEffectiveMasterOverride.value) {
    speedToSet = masterOverrideSpeed.value;
  } else {
    speedToSet = Math.round(speedToSet * (speedPercentage.value / 100));
  }

  // Cap to min/max safety boundaries
  speedToSet = Math.min(maxRpm.value, Math.max(minRpm.value, speedToSet));

  runningState.value = action;

  toolStore.sendSpindleCommand(
      props.tool.id,
      action as "forward" | "backward",
      speedToSet,
      masterOverrideSpeed.value,
      isEffectiveMasterOverride.value,
      isEffectiveMasterOverride.value ? 1.0 : speedPercentage.value / 100,
  );
}

// Debounced slider-drag dispatch.
watch([masterOverrideSpeed, speedPercentage], () => {
  if (runningState.value === "idle" || runningState.value === "stop") return;
  if (isDisabled.value) return;

  if (postTimer) clearTimeout(postTimer);
  postTimer = setTimeout(() => {
    postTimer = null;
    const action = runningState.value;

    if (isEffectiveMasterOverride.value) {
      toolStore.sendSpindleCommand(
          props.tool.id,
          action as "forward" | "backward",
          0,
          masterOverrideSpeed.value,
          true,
          1.0,
      );
    } else {
      toolStore.sendSpindleCommand(
          props.tool.id,
          action as "forward" | "backward",
          0,
          0,
          false,
          speedPercentage.value / 100,
      );
    }
  }, 1000);
});

onBeforeUnmount(() => {
  if (postTimer) clearTimeout(postTimer);
});
</script>

<template>
  <div class="flex gap-6 bg-gray-900/40 p-4 rounded-lg border border-gray-700 shadow-sm w-full transition-opacity"
       :class="{ 'opacity-60': isDisabled }">

    <!-- LEFT COLUMN: Controls -->
    <div class="flex-1 flex flex-col gap-4">

      <!-- Controls Wrapper (Disables pointer events if machine is offline/estopped) -->
      <div class="flex-1 flex flex-col gap-4" :class="{ 'pointer-events-none': isDisabled }">

        <!-- Auto Feed/Speed Section (Hidden in Manual Only mode) -->
        <div v-if="!isManualOnly" class="flex flex-col gap-2 bg-gray-800/40 p-4 rounded-md border border-gray-700/50">
          <div class="flex justify-between items-center">
            <span class="text-sm font-semibold text-gray-300">Auto Feed/Speed</span>
            <span class="text-xl font-mono text-blue-400 font-bold">{{ speedPercentage }}%</span>
          </div>

          <input
              v-model.number="speedPercentage"
              type="range"
              min="10"
              max="200"
              step="1"
              class="w-full h-2.5 bg-gray-700 rounded-lg appearance-none outline-none accent-blue-500 cursor-pointer my-1"
          >

          <span class="text-[11px] text-gray-500 leading-tight">
            Scales the programmed machine speed dynamically.
          </span>
        </div>

        <!-- Master Override / Manual Control Section -->
        <div class="bg-gray-800/60 p-4 rounded-md border flex flex-col gap-3 transition-colors"
             :class="isEffectiveMasterOverride ? 'border-blue-500/50' : 'border-gray-700'">

          <div class="flex items-center gap-3">
            <!-- Normal Mode Checkbox -->
            <template v-if="!isManualOnly">
              <input
                  id="master-override"
                  v-model="masterOverride"
                  type="checkbox"
                  class="w-5 h-5 accent-blue-500 cursor-pointer rounded bg-gray-900 border-gray-600"
              >
              <label for="master-override" class="text-sm font-semibold text-white cursor-pointer select-none">
                Master Override Mode
              </label>
            </template>
            <!-- Manual Mode Label -->
            <template v-else>
              <span class="text-sm font-semibold text-white select-none">
                Manual Control
              </span>
            </template>
          </div>

          <div class="flex flex-col gap-2" :class="{ 'opacity-40 grayscale': !isEffectiveMasterOverride }">
            <div class="flex justify-between items-end text-xs text-gray-400 font-mono">
              <span>{{ minRpm }}</span>
              <span class="text-blue-300 text-sm bg-gray-900 px-2 py-1 rounded">{{ masterOverrideSpeed }} RPM</span>
              <span>{{ maxRpm }}</span>
            </div>
            <input
                v-model.number="masterOverrideSpeed"
                type="range"
                :min="minRpm"
                :max="maxRpm"
                step="100"
                class="w-full h-2.5 bg-gray-900 rounded-lg appearance-none cursor-pointer accent-blue-500"
            >
          </div>
        </div>

        <!-- Action Buttons -->
        <div class="grid grid-cols-3 gap-3">
          <button
              type="button"
              class="py-2.5 bg-gray-700 hover:bg-gray-600 text-white rounded font-bold shadow-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="isDisabled"
              @click="handleSpindle('backward')"
          >
            Reverse
          </button>
          <button
              type="button"
              class="py-2.5 bg-red-600 hover:bg-red-500 text-white rounded font-bold shadow-md transition-colors tracking-widest disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="isDisabled"
              @click="handleSpindle('stop')"
          >
            STOP
          </button>
          <button
              type="button"
              class="py-2.5 bg-green-600 hover:bg-green-500 text-white rounded font-bold shadow-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="isDisabled"
              @click="handleSpindle('forward')"
          >
            Forward
          </button>
        </div>
      </div>

      <!-- Status Indicators -->
      <div class="flex justify-between items-center mt-auto pt-3 border-t border-gray-800 text-xs font-mono">
        <div class="flex items-center gap-2 bg-gray-900 px-3 py-1.5 rounded-full border border-gray-800">
          <span class="text-gray-400">Connected:</span>
          <div
              class="w-2.5 h-2.5 rounded-full"
              :class="tool.isConnected ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)]' : 'bg-red-500'"
          ></div>
          <span :class="tool.isConnected ? 'text-emerald-400' : 'text-red-400'" class="font-bold">
              {{ tool.isConnected ? "YES" : "NO" }}
            </span>
        </div>

        <div class="flex items-center gap-2 bg-gray-900 px-3 py-1.5 rounded-full border border-gray-800">
          <span class="text-gray-400">Errors:</span>
          <span :class="tool.errorCount > 0 ? 'text-red-400' : 'text-amber-400'" class="font-bold text-sm">
              {{ tool.errorCount }}
            </span>
        </div>
      </div>
    </div>

    <!-- RIGHT COLUMN: Vertical Speed Bar -->
    <div class="w-20 flex flex-col items-center gap-3 bg-gray-800/40 p-2 rounded-md border border-gray-700/50 flex-shrink-0">
      <div class="text-[10px] text-gray-400 uppercase tracking-widest text-center font-bold">
        Actual<br>RPM
      </div>

      <!-- Gradient Bar Container -->
      <div class="flex-1 w-8 relative rounded-full overflow-hidden border-2 border-gray-900 shadow-inner bg-gray-800">
        <!-- Colored Background Gauge -->
        <div class="absolute inset-0" :style="gaugeGradient"></div>
        <!-- Black/Gray mask sliding down to reveal colors -->
        <div
            class="absolute top-0 w-full bg-gray-800 transition-all duration-300 ease-out border-b border-gray-900 shadow-sm"
            :style="{ height: gaugeCoverHeight }"
        ></div>
      </div>

      <div class="text-sm font-mono text-white font-bold bg-gray-900 w-full text-center py-1 rounded">
        {{ actualRpm }}
      </div>
    </div>

  </div>
</template>

<style scoped>
/* Base customizer for range thumb (horizontal) to match dashboard aesthetic */
input[type="range"]:not(.slider-vertical)::-webkit-slider-thumb {
  -webkit-appearance: none;
  height: 18px;
  width: 18px;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
  box-shadow: 0 0 5px rgba(0, 0, 0, 0.5);
  margin-top: -4px;
}

input[type="range"]:not(.slider-vertical)::-moz-range-thumb {
  height: 18px;
  width: 18px;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
  border: none;
  box-shadow: 0 0 5px rgba(0, 0, 0, 0.5);
}
</style>