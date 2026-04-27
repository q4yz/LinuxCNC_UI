<script setup>
import { storeToRefs } from 'pinia'
import { useMachineStore } from '../stores/machine'

const store = useMachineStore()
// Destructure reactive properties with storeToRefs to maintain reactivity
const { droX, droY, droZ, isEstop, isMachineOn, machineStateText, status } = storeToRefs(store)
</script>

<template>
  <div class="flex flex-col space-y-6">
    <!-- Top Banner for ESTOP / Machine State -->
    <div 
      class="rounded-lg p-4 flex items-center justify-between shadow-lg"
      :class="isEstop ? 'bg-red-900 border border-red-500' : 'bg-gray-800 border border-gray-700'"
    >
      <div class="flex items-center space-x-4">
        <div class="text-2xl font-bold uppercase tracking-widest">
          STATE: {{ machineStateText }}
        </div>
      </div>
      
      <!-- Placeholder Buttons for Machine Control -->
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

    <!-- DRO (Digital Readout) Panel -->
    <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden">
      <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600">
        <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">Toolhead / DRO</h2>
      </div>
      
      <div class="p-6 space-y-4 font-mono text-3xl text-right tracking-tight">
        <div class="flex justify-between items-center bg-gray-900 px-4 py-3 rounded border border-gray-800">
          <span class="text-red-500 font-bold mr-4">X</span>
          <span class="text-gray-100">{{ droX }}</span>
        </div>
        
        <div class="flex justify-between items-center bg-gray-900 px-4 py-3 rounded border border-gray-800">
          <span class="text-green-500 font-bold mr-4">Y</span>
          <span class="text-gray-100">{{ droY }}</span>
        </div>
        
        <div class="flex justify-between items-center bg-gray-900 px-4 py-3 rounded border border-gray-800">
          <span class="text-blue-500 font-bold mr-4">Z</span>
          <span class="text-gray-100">{{ droZ }}</span>
        </div>
      </div>
      
      <div class="bg-gray-700/30 px-4 py-3 flex justify-between text-sm text-gray-400">
        <span>Machine Pos</span>
        <span v-if="status.homed.every(h => h === 1)" class="text-green-400">Homed</span>
        <span v-else class="text-yellow-500">Un-homed</span>
      </div>
    </div>
  </div>
</template>
