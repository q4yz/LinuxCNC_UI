<script setup lang="ts">
import {storeToRefs} from "pinia";
import useMachineStore from "../../stores/machine";
import {useBaseThreadStore} from "../../stores/baseThread";
import {useConsoleStore} from "../../stores/console";
import {computed, ref} from "vue";
import BaseRange from "../../ui/BaseRange.vue";
import BaseCard from "../../ui/BaseCard.vue";

const store = useMachineStore()
const consoleStore = useConsoleStore()
const {  isMachineOn } = storeToRefs(store)
const { maxAxisVelocity } = storeToRefs(useBaseThreadStore())

// Slider top = max of all axis velocity limits (mm/s → mm/min), the
// machine's own [AXIS_*] MAX_VELOCITY. ``null`` until known — the
// slider is disabled rather than sized from a guessed 5000 mm/min.
const maxSpeedLimit = computed<number | null>(() =>
    maxAxisVelocity.value === null ? null : Math.round(maxAxisVelocity.value * 60))

// The backend does not report feed override / max velocity back, so both
// start unknown (no assumed defaults). A successful command is the only
// confirmation we get: on ``ok`` we wire the requested value in, which is
// what ``BaseRange`` waits for. A failure leaves the ref untouched and
// ``BaseRange`` reverts after its sync timeout.
const speedMultiplier = ref<number | null>(null) // %
const maxSpeed = ref<number | null>(null) // mm/min

// ``/axis/settings`` takes both values in one call. Until the operator has
// set both, a change is staged locally and nothing is sent.
async function applyAxisSettings(multiplierPct: number | null, limit: number | null) {
  if (multiplierPct === null || limit === null) {
    const missing = multiplierPct === null ? 'Speed Multiplier' : 'Max Speed'
    consoleStore.warning(`Axis speed staged, not sent: set ${missing} too — the backend only accepts both together`)
    return true
  }
  const result = await store.updateAxisSettings(multiplierPct / 100, limit)
  return result.ok
}

async function handleSpeedMultiplierChange(value: number) {
  if (await applyAxisSettings(value, maxSpeed.value)) speedMultiplier.value = value
}

async function handleMaxSpeedChange(value: number) {
  if (await applyAxisSettings(speedMultiplier.value, value)) maxSpeed.value = value
}
</script>

<template>


  <BaseCard class="p-4">
    <!-- Speed Multiplier (Feed Override) -->
    <div>
      <BaseRange
          :model-value="speedMultiplier"
          label="Speed Multiplier"
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
