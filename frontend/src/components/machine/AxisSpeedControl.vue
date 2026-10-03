<script setup lang="ts">
import {storeToRefs} from "pinia";
import useMachineStore from "../../stores/machine";
import {useBaseThreadStore} from "../../stores/baseThread";
import {useConsoleStore} from "../../stores/console";
import {computed} from "vue";
import BaseRange from "../../ui/BaseRange.vue";
import BaseCard from "../../ui/BaseCard.vue";

const store = useMachineStore()
const consoleStore = useConsoleStore()
const {  isMachineOn } = storeToRefs(store)
const { maxAxisVelocity, speedOverride } = storeToRefs(useBaseThreadStore())

// Slider top = max of all axis velocity limits (mm/s → mm/min), the
// machine's own [AXIS_*] MAX_VELOCITY. ``null`` until known — the
// slider is disabled rather than sized from a guessed 5000 mm/min.
const maxSpeedLimit = computed<number | null>(() =>
    maxAxisVelocity.value === null ? null : Math.round(maxAxisVelocity.value * 60))

// Both sliders show what LinuxCNC actually applies — the base-thread
// store's ``speedOverride`` (stat.feedrate / stat.max_velocity, 1 Hz).
// ``null`` until reported. BaseRange keeps a requested value on screen
// until this read-back echoes it, or reverts after its sync timeout.
const speedMultiplier = computed(() => speedOverride.value.feedOverridePercent) // %
const maxSpeed = computed(() => speedOverride.value.maxVelocityMmPerMin) // mm/min

// ``/axis/settings`` takes both values in one call, so a change re-sends
// the other one's *current backend* value. While that is unknown nothing
// can be sent without inventing it — refuse loudly instead.
async function applyAxisSettings(multiplierPct: number | null, limit: number | null, changed: string) {
  if (multiplierPct === null || limit === null) {
    const missing = multiplierPct === null ? 'Speed Multiplier' : 'Max Speed'
    consoleStore.warning(`${changed} not sent: ${missing} not reported by the backend yet — both are sent together`)
    return
  }
  // The endpoint takes whole mm/min; a read-back like 4199.4 would 422.
  await store.updateAxisSettings(multiplierPct / 100, Math.round(limit))
}

function handleSpeedMultiplierChange(value: number) {
  void applyAxisSettings(value, maxSpeed.value, 'Speed Multiplier')
}

function handleMaxSpeedChange(value: number) {
  void applyAxisSettings(speedMultiplier.value, value, 'Max Speed')
}
</script>

<template>


  <BaseCard class="p-4">
    <!-- Speed Multiplier (Feed Override) -->
    <div>
      <BaseRange
          :model-value="speedMultiplier"
          label="Speed Multiplier"
          :tolerance="0.5"
          @update:model-value="handleSpeedMultiplierChange"
          min="0"
          max="400"
          step="1"
          :disabled="!isMachineOn"
      >
        <template #header="{ value }">
          <div class="flex justify-between items-end mb-2">
            <label class="text-sm font-semibold text-gray-300 uppercase tracking-wider">Speed Multiplier</label>
            <span class="font-mono text-lg text-blue-400 font-bold">{{ value ?? '—' }}%</span>
          </div>
        </template>
      </BaseRange>
    </div>

    <!-- Max Speed (Absolute) -->
    <div>
      <BaseRange
          :model-value="maxSpeed"
          label="Max Speed"
          :tolerance="1"
          @update:model-value="handleMaxSpeedChange"
          min="0"
          :max="maxSpeedLimit ?? undefined"
          step="10"
          :disabled="!isMachineOn || maxSpeedLimit === null"
      >
        <template #header="{ value }">
          <div class="flex justify-between items-end mb-2">
            <label class="text-sm font-semibold text-gray-300 uppercase tracking-wider">Max Speed</label>
            <span class="font-mono text-lg text-blue-400 font-bold">{{ value ?? '—' }} mm/min</span>
          </div>
        </template>
      </BaseRange>
    </div>

  </BaseCard>

</template>

<style scoped>

</style>
