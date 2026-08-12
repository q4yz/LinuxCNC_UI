<script setup>
import {ref, computed} from "vue";
import {useToolStore} from "../toolStore.js";

const props = defineProps({
  tool: {type: Object, required: true},
});

const toolStore = useToolStore();

// Local working state
const speedPercentage = ref(100);
const manualOverride = ref(false);
const manualSpeed = ref(props.tool.min_rpm ?? 0);

// Computed bounds and values
const minRpm = computed(() => props.tool.min_rpm ?? 0);
const maxRpm = computed(() => props.tool.max_rpm ?? 24000);
const actualRpm = computed(() => props.tool.actual_rpm ?? 0);

// Calculate the percentage of the minimum RPM relative to max for the gradient stops
const minPercent = computed(() => {
  if (!maxRpm.value) return 0;
  return (minRpm.value / maxRpm.value) * 100;
});

// Dynamic gradient background for the RPM gauge
// Red below min_rpm, Orange in the middle, Green near the top (last 20%)
const gaugeGradient = computed(() => {
  return {
    background: `linear-gradient(to top,
      #ef4444 0%, #ef4444 ${minPercent.value}%,
      #f97316 ${minPercent.value}%, #f97316 80%,
      #22c55e 80%, #22c55e 100%)`
  };
});

// The height of the "mask" that hides the upper portion of the gradient gauge
const gaugeCoverHeight = computed(() => {
  if (!maxRpm.value) return '100%';
  const pct = Math.min(100, Math.max(0, (actualRpm.value / maxRpm.value) * 100));
  return `${100 - pct}%`;
});

// Issue commands to the spindle
function handleSpindle(action) {
  if (action === "stop") {
    toolStore.sendSpindleCommand(props.tool.id, "stop", 0);
    return;
  }

  // Determine the speed based on override modes
  let speedToSet = props.tool.set_speed ?? 0;

  if (manualOverride.value) {
    speedToSet = manualSpeed.value;
  } else {
    // Apply automatic percentage correction to programmed speed
    speedToSet = Math.round(speedToSet * (speedPercentage.value / 100));
  }

  // Cap to min/max safety boundaries
  speedToSet = Math.min(maxRpm.value, Math.max(minRpm.value, speedToSet));

  toolStore.sendSpindleCommand(props.tool.id, action, speedToSet);
}
</script>

<template>
  <div class="flex gap-6 bg-gray-900/40 p-4 rounded-lg border border-gray-700 shadow-sm w-full">

    <!-- LEFT COLUMN: Controls (flex-1 makes it maximize space) -->
    <div class="flex-1 flex flex-col gap-4">

      <!-- Auto Feed/Speed Section -->
      <div class="flex flex-col gap-2 bg-gray-800/40 p-4 rounded-md border border-gray-700/50">
        <!-- Header row with title and percentage -->
        <div class="flex justify-between items-center">
          <span class="text-sm font-semibold text-gray-300">Auto Feed/Speed</span>
          <span class="text-xl font-mono text-blue-400 font-bold">{{ speedPercentage }}%</span>
        </div>

        <!-- Horizontal Slider -->
        <input
            v-model.number="speedPercentage"
            type="range"
            min="10"
            max="200"
            step="1"
            class="w-full h-2.5 bg-gray-700 rounded-lg appearance-none outline-none accent-blue-500 cursor-pointer my-1"
        >

        <!-- Description -->
        <span class="text-[11px] text-gray-500 leading-tight">
          Scales the programmed machine speed dynamically.
        </span>
      </div>

      <!-- Manual Override Section -->
      <div class="bg-gray-800/60 p-4 rounded-md border border-gray-700 flex flex-col gap-3 transition-colors"
           :class="manualOverride ? 'border-blue-500/50' : ''">
        <div class="flex items-center gap-3">
          <input
              id="manual-override"
              v-model="manualOverride"
              type="checkbox"
              class="w-5 h-5 accent-blue-500 cursor-pointer rounded bg-gray-900 border-gray-600"
          >
          <label for="manual-override" class="text-sm font-semibold text-white cursor-pointer select-none">
            Manual Override Mode
          </label>
        </div>

        <div class="flex flex-col gap-2" :class="{ 'opacity-40 pointer-events-none grayscale': !manualOverride }">
          <div class="flex justify-between items-end text-xs text-gray-400 font-mono">
            <span>{{ minRpm }}</span>
            <span class="text-blue-300 text-sm bg-gray-900 px-2 py-1 rounded">{{ manualSpeed }} RPM</span>
            <span>{{ maxRpm }}</span>
          </div>
          <input
              v-model.number="manualSpeed"
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
            class="py-2.5 bg-gray-700 hover:bg-gray-600 text-white rounded font-bold shadow-md transition-colors"
            @click="handleSpindle('backward')"
        >
          Reverse
        </button>
        <button
            type="button"
            class="py-2.5 bg-red-600 hover:bg-red-500 text-white rounded font-bold shadow-md transition-colors tracking-widest"
            @click="handleSpindle('stop')"
        >
          STOP
        </button>
        <button
            type="button"
            class="py-2.5 bg-green-600 hover:bg-green-500 text-white rounded font-bold shadow-md transition-colors"
            @click="handleSpindle('forward')"
        >
          Forward
        </button>
      </div>

      <!-- Status Indicators -->
      <div class="flex justify-between items-center mt-auto pt-3 border-t border-gray-800 text-xs font-mono">
        <div class="flex items-center gap-2 bg-gray-900 px-3 py-1.5 rounded-full border border-gray-800">
          <span class="text-gray-400">Connected:</span>
          <div
              class="w-2.5 h-2.5 rounded-full"
              :class="tool.is_connected ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)]' : 'bg-red-500'"
          ></div>
          <span :class="tool.is_connected ? 'text-emerald-400' : 'text-red-400'" class="font-bold">
              {{ tool.is_connected ? "YES" : "NO" }}
            </span>
        </div>

        <div class="flex items-center gap-2 bg-gray-900 px-3 py-1.5 rounded-full border border-gray-800">
          <span class="text-gray-400">Errors:</span>
          <span :class="tool.error_count > 0 ? 'text-red-400' : 'text-amber-400'" class="font-bold text-sm">
              {{ tool.error_count ?? 0 }}
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