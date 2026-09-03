<script setup lang="ts">


import {storeToRefs} from "pinia";
import useBaseThreadStore from "../../stores/baseThread";
import useMachineStore from "../../stores/machine";
import {ref} from "vue";
import BaseRange from "../../ui/BaseRange.vue";
import BaseCard from "../../ui/BaseCard.vue";

const store = useMachineStore()
const baseThreadStore = useBaseThreadStore()
const {  isMachineOn } = storeToRefs(store)


// Speed controls state (initialized to default values)
const speedMultiplier = ref(100) // 100%
const maxSpeed = ref(1000) // mm/min or unit/min


async function handleSpeedMultiplierChange() {
  await store.updateAxisSettings(speedMultiplier.value / 100, maxSpeed.value)
}

async function handleMaxSpeedChange() {
  await store.updateAxisSettings(speedMultiplier.value / 100, maxSpeed.value)
}
</script>

<template>


  <BaseCard class="p-4">
    <!-- Speed Multiplier (Feed Override) -->
    <div>
      <div class="flex justify-between items-end mb-2">
        <label class="text-sm font-semibold text-gray-300 uppercase tracking-wider">Speed Multiplier</label>
        <span class="font-mono text-lg text-blue-400 font-bold">{{ speedMultiplier }}%</span>
      </div>
      <BaseRange
          v-model="speedMultiplier"
          @change="handleSpeedMultiplierChange"
          min="0"
          max="400"
          step="1"
          :disabled="!isMachineOn"
      />
    </div>

    <!-- Max Speed (Absolute) -->
    <div>
      <div class="flex justify-between items-end mb-2">
        <label class="text-sm font-semibold text-gray-300 uppercase tracking-wider">Max Speed</label>
        <span class="font-mono text-lg text-blue-400 font-bold">{{ maxSpeed }} mm/min</span>
      </div>
      <BaseRange
          v-model="maxSpeed"
          @change="handleMaxSpeedChange"
          min="0"
          max="5000"
          step="10"
          :disabled="!isMachineOn"
      />
    </div>

  </BaseCard>

</template>

<style scoped>

</style>