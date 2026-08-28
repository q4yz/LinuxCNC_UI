<script setup lang="ts">

import {storeToRefs} from "pinia";
import useMachineStore from "../../stores/machine";


const store = useMachineStore()

const {  isEstop, isMachineOn, machineStateText } = storeToRefs(store)



</script>

<template>
  <div
      class="rounded-lg p-4 flex items-center justify-between shadow-lg"
      :class="isEstop ? 'bg-red-900 border border-red-500' : 'bg-gray-800 border border-gray-700'"
  >
    <div class="flex items-center space-x-4">
      <div class="text-2xl font-bold uppercase tracking-widest">
        STATE: {{ machineStateText }}
      </div>
    </div>

    <!-- Machine Control Buttons -->
    <div class="flex space-x-3">
      <button
          @click="store.toggleEstop()"
          class="px-4 py-2 rounded font-bold transition-colors"
          :class="isEstop ? 'bg-red-600 hover:bg-red-500 text-white' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'"
      >
        E-STOP
      </button>
      <button
          @click="store.togglePower()"
          class="px-4 py-2 rounded font-bold transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          :class="isMachineOn ? 'bg-green-600 hover:bg-green-500 text-white' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'"
          :disabled="isEstop && !isMachineOn"
      >
        POWER
      </button>
    </div>
  </div>
</template>

<style scoped>

</style>