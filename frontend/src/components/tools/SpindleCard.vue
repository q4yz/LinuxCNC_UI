<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { storeToRefs } from "pinia";

import { useToolStore } from "../../stores/toolsStore";
import { SpindleDigital } from "../../entities/tools";
import { SystemState, useMachineStore } from "../../stores/stateFacade";

const props = defineProps<{
  tool: SpindleDigital;
}>();

const toolStore = useToolStore();

const { systemState } = storeToRefs(useMachineStore());

// --- Local working state -------------------------------------------------

// speedPercentage holds the raw backend float (e.g., 1.0 for 100%)
const speedPercentage = ref<number | null>(null);
const masterOverride = ref<boolean | null>(null);
const masterOverrideSpeed = ref<number | null>(null);

type SpindleRunningState = "forward" | "backward" | "stop";

const runningState = ref<SpindleRunningState>("stop");
let postTimer: ReturnType<typeof setTimeout> | null = null;
let suppressSyncUntil = 0; // Timestamp lock to prevent rubber-banding

// --- State Logic ---

const isDisabled = computed(() => {
  return [
    SystemState.OFFLINE,
    SystemState.POWER_OFF,
    SystemState.ESTOP,
    SystemState.UPDATING
  ].includes(systemState.value);
});

const isManualOnly = computed(() => {
  return [
    SystemState.IDLE,
    SystemState.LOADED,
    SystemState.FAILURE
  ].includes(systemState.value);
});

const isEffectiveMasterOverride = computed(() => isManualOnly.value || masterOverride.value === true);

// --- RPM Logic ---

const minRpm = computed<number | null>(() => props.tool.minRpm);
const maxRpm = computed<number | null>(() => props.tool.maxRpm);
const actualRpm = computed<number | null>(() => props.tool.actualRpm);

const rangeMinRpm = computed(() => minRpm.value ?? 0);
const rangeMaxRpm = computed(() => maxRpm.value ?? 24000);

const SPEED_PERCENT_MIN = 10;
const SPEED_PERCENT_MAX = 200;

// Writable computed to bridge the UI scale (10-200) with the backend float (0.1-2.0)
const sliderSpeedPercent = computed({
  get: () => speedPercentage.value === null ? 100 : Math.round(speedPercentage.value * 100),
  set: (val: number) => {
    speedPercentage.value = val / 100;
  }
});

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
  const pct = Math.min(100, Math.max(0, ((actualRpm.value ?? 0) / maxRpm.value) * 100));
  return `${100 - pct}%`;
});

// --- Sync from HAL pin (snapshot) ----------------------------------------
watch(
    () => [
      props.tool.override,
      props.tool.masterOverride,
      props.tool.masterOverrideEnable,
      props.tool.direction,
    ],
    ([newOverride, newMasterOverride, newMasterOverrideEnable, newDirection]) => {
      const isDragging = postTimer !== null;

      // Prevent UI rubber-banding: Ignore incoming snapshots while dragging
      // OR immediately after dispatching (waiting for the backend to process the new values).
      if (isDragging || Date.now() < suppressSyncUntil) {
        // If the incoming snapshot exactly matches our optimistic local state,
        // the backend has processed our command. We can release the suppression lock early.
        const isAcknowledged =
            newOverride === speedPercentage.value &&
            newMasterOverride === masterOverrideSpeed.value &&
            newMasterOverrideEnable === masterOverride.value &&
            newDirection === runningState.value;

        if (isAcknowledged) {
          suppressSyncUntil = 0;
        } else {
          return; // Ignore stale snapshot
        }
      }

      if (speedPercentage.value !== newOverride) speedPercentage.value = newOverride;
      if (masterOverrideSpeed.value !== newMasterOverride) masterOverrideSpeed.value = newMasterOverride;
      if (masterOverride.value !== newMasterOverrideEnable) masterOverride.value = newMasterOverrideEnable;
      if (runningState.value !== newDirection) runningState.value = newDirection;
    },
    { immediate: true },
);

// --- Display formatting --------------------------------------------------

const PLACEHOLDER = "--";

const masterOverrideRpmLabel = computed(() =>
    masterOverrideSpeed.value === null ? PLACEHOLDER : Math.round(masterOverrideSpeed.value)
);

const isSpeedSliderDisabled = computed(() => isDisabled.value || speedPercentage.value === null);
const isMasterSliderDisabled = computed(() =>
    isDisabled.value ||
    masterOverrideSpeed.value === null ||
    minRpm.value === null ||
    maxRpm.value === null
);
const isMasterCheckboxDisabled = computed(() => isDisabled.value || masterOverride.value === null);

// --- Actions ---

function handleSpindle(action: SpindleRunningState) {
  if (isDisabled.value) return;

  runningState.value = action;
  suppressSyncUntil = Date.now() + 300;

  if (action === "stop") {
    toolStore.sendSpindleCommand(
        props.tool.id,
        "stop",
        0,
        masterOverrideSpeed.value ?? 0,
        false,
        1.0,
    );
    return;
  }

  let speedToSet = props.tool.actualRpm ?? 0;

  if (isEffectiveMasterOverride.value) {
    speedToSet = masterOverrideSpeed.value ?? 0;
  } else {
    const percent = speedPercentage.value ?? 1.0;
    speedToSet = Math.round(speedToSet * percent);
  }

  toolStore.sendSpindleCommand(
      props.tool.id,
      action as "forward" | "backward",
      speedToSet,
      masterOverrideSpeed.value ?? 0,
      isEffectiveMasterOverride.value,
      isEffectiveMasterOverride.value ? 1.0 : (speedPercentage.value ?? 1.0),
  );
}

// Debounced slider-drag / checkbox-toggle dispatch.
watch([masterOverrideSpeed, speedPercentage, masterOverride], ([newMaster, newPercent, newMasterEnable]) => {
  if (isDisabled.value) return;

  // Anti-echo: If the local values perfectly match the backend props,
  // this change was triggered by the sync watcher. Do not dispatch.
  if (
      newMaster === props.tool.masterOverride &&
      newPercent === props.tool.override &&
      newMasterEnable === props.tool.masterOverrideEnable
  ) {
    return;
  }

  if (postTimer) clearTimeout(postTimer);
  postTimer = setTimeout(() => {
    postTimer = null;
    suppressSyncUntil = Date.now() + 2000; // Ignore stale backend snapshots for 2s after slider release

    // Always send the current action so slider updates persist even when stopped
    const action = runningState.value;

    if (isEffectiveMasterOverride.value) {
      toolStore.sendSpindleCommand(
          props.tool.id,
          action,
          0,
          masterOverrideSpeed.value ?? 0,
          true,
          1.0,
      );
    } else {
      toolStore.sendSpindleCommand(
          props.tool.id,
          action,
          0,
          0,
          false,
          speedPercentage.value ?? 1.0,
      );
    }
  }, 750);
});

onBeforeUnmount(() => {
  if (postTimer) clearTimeout(postTimer);
});
</script>

<template>
  <!-- Added min-w-[380px] and overflow-x-auto -->
  <div class="flex gap-6 bg-gray-900/40  rounded-lg border border-gray-700 shadow-sm w-full min-w-[250px] overflow-x-auto transition-opacity"
       :class="{ 'opacity-60': isDisabled }">

    <!-- LEFT COLUMN: Controls -->
    <!-- Added min-w-[260px] -->
    <div class="flex-1 flex flex-col gap-4 min-w-[150px]">

      <!-- Controls Wrapper -->
      <div class="flex-1 flex flex-col gap-4" :class="{ 'pointer-events-none': isDisabled }">

        <!-- Auto Feed/Speed Section -->
        <div v-if="!isManualOnly" class="flex flex-col gap-2 bg-gray-800/40 p-4 rounded-md border border-gray-700/50">
          <div class="flex justify-between items-center">
            <span class="text-sm font-semibold text-gray-300 whitespace-nowrap">Auto Feed/Speed</span>
            <span class="text-xl font-mono text-blue-400 font-bold shrink-0 ml-2">
              <template v-if="speedPercentage === null">
                <span class="text-gray-600 italic">{{ PLACEHOLDER }}%</span>
              </template>
              <template v-else>
                {{ sliderSpeedPercent }}%
              </template>
            </span>
          </div>

          <input
              v-model.number="sliderSpeedPercent"
              type="range"
              :min="SPEED_PERCENT_MIN"
              :max="SPEED_PERCENT_MAX"
              step="1"
              :disabled="isSpeedSliderDisabled"
              class="w-full h-2.5 bg-gray-700 rounded-lg appearance-none outline-none accent-blue-500 my-1 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
          >

          <span class="text-[11px] text-gray-500 leading-tight">
            Scales the programmed machine speed dynamically.
          </span>
        </div>

        <!-- Master Override / Manual Control Section -->
        <div class="bg-gray-800/60 p-4 rounded-md border flex flex-col gap-3 transition-colors"
             :class="isEffectiveMasterOverride ? 'border-blue-500/50' : 'border-gray-700'">

          <div class="flex items-center gap-3">
            <template v-if="!isManualOnly">
              <input
                  id="master-override"
                  v-model="masterOverride"
                  type="checkbox"
                  :disabled="isMasterCheckboxDisabled"
                  :indeterminate.prop="masterOverride === null"
                  class="w-5 h-5 accent-blue-500 rounded bg-gray-900 border-gray-600 shrink-0 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              >
              <label for="master-override" class="text-sm font-semibold text-white select-none whitespace-nowrap"
                     :class="{ 'cursor-pointer': !isMasterCheckboxDisabled, 'cursor-not-allowed text-gray-500': isMasterCheckboxDisabled }">
                Master Override Mode
              </label>
            </template>
            <template v-else>
              <span class="text-sm font-semibold text-white select-none whitespace-nowrap">
                Manual Control
              </span>
            </template>
          </div>

          <div class="flex flex-col gap-2" :class="{ 'opacity-40 grayscale': !isEffectiveMasterOverride }">
            <div class="flex justify-between items-end text-xs text-gray-400 font-mono">
              <span class="shrink-0">{{ minRpm === null ? PLACEHOLDER : minRpm }}</span>
              <span class="text-blue-300 text-sm bg-gray-900 px-2 py-1 rounded shrink-0 mx-2">
                <template v-if="masterOverrideSpeed === null">
                  <span class="text-gray-600 italic">{{ PLACEHOLDER }} RPM</span>
                </template>
                <template v-else>
                  {{ masterOverrideRpmLabel }} RPM
                </template>
              </span>
              <span class="shrink-0">{{ maxRpm === null ? PLACEHOLDER : maxRpm }}</span>
            </div>
            <input
                v-model.number="masterOverrideSpeed"
                type="range"
                :min="rangeMinRpm"
                :max="rangeMaxRpm"
                step="100"
                :disabled="isMasterSliderDisabled"
                class="w-full h-2.5 bg-gray-900 rounded-lg appearance-none accent-blue-500 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
            >
          </div>
        </div>

        <!-- Action Buttons (tightened gap and dynamic text) -->
        <template v-if="isManualOnly">

        <div class="grid grid-cols-3 gap-2">
          <button
              type="button"
              class="py-2.5 bg-gray-700 hover:bg-gray-600 text-white rounded text-sm md:text-base font-bold shadow-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="isDisabled"
              @click="handleSpindle('backward')"
          >
            Reverse
          </button>
          <button
              type="button"
              class="py-2.5 bg-red-600 hover:bg-red-500 text-white rounded text-sm md:text-base font-bold shadow-md transition-colors tracking-widest disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="isDisabled"
              @click="handleSpindle('stop')"
          >
            STOP
          </button>
          <button
              type="button"
              class="py-2.5 bg-green-600 hover:bg-green-500 text-white rounded text-sm md:text-base font-bold shadow-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="isDisabled"
              @click="handleSpindle('forward')"
          >
            Forward
          </button>
        </div>
        </template>
      </div>


      <!-- Status Indicators -->
     <div class="flex justify-between items-center mt-auto pt-3 border-t border-gray-800 text-xs font-mono">
    <div class="flex items-center gap-2 bg-gray-900 px-3 py-1.5 rounded-full border border-gray-800 shrink-0">
      <span class="text-gray-400">Conn:</span>
      <div
          class="w-2.5 h-2.5 rounded-full shrink-0"
          :class="tool.isConnected ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)]' : 'bg-red-500'"
      ></div>
      <span :class="tool.isConnected ? 'text-emerald-400' : 'text-red-400'" class="font-bold">
          {{ tool.isConnected ? "YES" : "NO" }}
        </span>
    </div>

    <div class="flex items-center gap-2 bg-gray-900 px-3 py-1.5 rounded-full border border-gray-800 shrink-0">
      <span class="text-gray-400">Err:</span>
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
        <template v-if="actualRpm === null">
          <span class="text-gray-600 italic">{{ PLACEHOLDER }}</span>
        </template>
        <template v-else>
          {{ actualRpm }}
        </template>
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