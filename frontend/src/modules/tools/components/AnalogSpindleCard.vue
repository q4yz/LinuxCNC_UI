<script setup>
// Analog spindle card — the spindle has no RPM feedback (typical
// of a VFD driven by a 0–10 V analogue signal), so the actual /
// target RPM tiles and the digital-spindle direction buttons are
// hidden. Only the commanded speed and an Enable / Disable pair
// remain. Reuses ``sendSpindleCommand`` with the existing actions
// (``forward`` ⇒ enable with ``set_speed``, ``stop`` ⇒ disable at 0)
// so no new store action is needed.
//
// Local ``setSpeed`` ref pattern — see SpindleCard.vue for the
// rationale (the base-thread snapshot replaces ``props.tool``
// every 1 s, so binding ``v-model`` to ``props.tool.set_speed``
// would wipe the typed value within a second).

import { computed, ref, watch } from "vue";

import { useToolStore } from "../toolStore.js";

const props = defineProps({
  tool: { type: Object, required: true },
});

const toolStore = useToolStore();

// Local working state — seeded from the snapshot on first arrival
// and re-seeded on chip switch. ``min_rpm`` fallback keeps the
// slider in a sensible position when no setpoint has been set.
const setSpeed = ref(0);

function seedFromTool() {
  const t = props.tool || {};
  setSpeed.value =
    typeof t.set_speed === "number" && t.set_speed > 0
      ? t.set_speed
      : (t.min_rpm ?? 0);
}
seedFromTool();
watch(() => props.tool?.id, seedFromTool);

// HTML range inputs require a definitive max value. Fall back to
// 24000 (a common spindle max) when the backend omits ``max_rpm``.
const minRpm = computed(() => props.tool?.min_rpm ?? 0);
const maxRpm = computed(() => props.tool?.max_rpm ?? 24000);

// State derived from the local slider value, not from the
// (unreliable) ``tool.target_rpm`` field.
const isRunning = computed(() => setSpeed.value > 0);

// Send the command when the user releases the slider knob.
function onSliderChange() {
  if (setSpeed.value > 0) {
    toolStore.sendSpindleCommand(
      props.tool.id,
      "forward",
      setSpeed.value,
    );
  } else {
    stopSpindle();
  }
}

// Force speed to 0 and send the stop command.
function stopSpindle() {
  setSpeed.value = 0;
  toolStore.sendSpindleCommand(props.tool.id, "stop", 0);
}
</script>

<template>
  <div class="space-y-4 bg-gray-900/50 p-4 rounded border border-gray-700">

    <!-- Header & State Indicator -->
    <div class="flex justify-between items-center">
      <p class="text-xs text-gray-400 italic">
        Analog spindle — slider controls speed
      </p>
      <div
        class="px-3 py-1 text-xs font-bold uppercase rounded shadow-sm"
        :class="isRunning ? 'bg-green-500/20 text-green-400 border border-green-500/30' : 'bg-gray-800 text-gray-500 border border-gray-700'"
      >
        State: {{ isRunning ? 'Running' : 'Stopped' }}
      </div>
    </div>

    <!-- Speed Slider -->
    <div class="flex flex-col gap-2 pt-2">
      <div class="flex justify-between items-end">
        <label class="block text-sm text-gray-300 font-medium">
          Speed: <span class="text-white font-mono text-base ml-1">{{ setSpeed }}</span> RPM
        </label>
      </div>

      <input
        v-model.number="setSpeed"
        type="range"
        :min="minRpm"
        :max="maxRpm"
        class="w-full h-3 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
        @change="onSliderChange"
      >

      <div class="flex justify-between text-[11px] text-gray-500 font-mono">
        <span>{{ minRpm }}</span>
        <span>{{ maxRpm }}</span>
      </div>
    </div>

    <!-- Stop Button -->
    <button
      type="button"
      class="w-full px-4 py-3 bg-red-600 hover:bg-red-500 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded font-bold tracking-widest shadow transition-colors flex justify-center items-center gap-2"
      :disabled="!isRunning"
      @click="stopSpindle"
    >
      <!-- Optional Stop Icon -->
      <svg v-if="isRunning" xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8 7a1 1 0 00-1 1v4a1 1 0 001 1h4a1 1 0 001-1V8a1 1 0 00-1-1H8z" clip-rule="evenodd" />
      </svg>
      STOP
    </button>
  </div>
</template>

<style scoped>
/* Customizing the slider knob (thumb) for better cross-browser aesthetics */
input[type=range]::-webkit-slider-thumb {
  -webkit-appearance: none;
  height: 20px;
  width: 20px;
  border-radius: 50%;
  background: #3b82f6; /* blue-500 */
  cursor: pointer;
  box-shadow: 0 0 4px rgba(0,0,0,0.5);
  margin-top: -1px;
}
input[type=range]::-moz-range-thumb {
  height: 20px;
  width: 20px;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
  border: none;
  box-shadow: 0 0 4px rgba(0,0,0,0.5);
}
</style>