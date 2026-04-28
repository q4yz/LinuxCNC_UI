<script setup>
import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useMachineStore } from '../stores/machine'
import { WORK_COORDINATE_SYSTEMS } from '../config/gcodes'

const store = useMachineStore()
// Destructure reactive properties with storeToRefs to maintain reactivity
const { droX, droY, droZ, isEstop, isMachineOn, machineStateText, status } = storeToRefs(store)

// Set Position modal state
const setPositionModal = ref({ visible: false, axis: null, axisName: '', value: '' })

function openSetPosition(axis, axisName, currentValue) {
  setPositionModal.value = { visible: true, axis, axisName, value: currentValue }
}

function closeSetPosition() {
  setPositionModal.value = { visible: false, axis: null, axisName: '', value: '' }
}

async function applySetPosition() {
  const { axis, value } = setPositionModal.value
  const parsed = parseFloat(value)
  if (!isFinite(parsed)) return
  await store.setPosition(axis, parsed)
  closeSetPosition()
}

function updateWcs(event) {
  const newIndex = parseInt(event.target.value)
  const system = WORK_COORDINATE_SYSTEMS.find(s => s.index === newIndex)
  if (system) {
    store.setCoordinateSystem(system.name)
  }
}
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

    <!-- DRO (Digital Readout) Panel -->
    <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden">
      <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex items-center justify-between">
        <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">Toolhead / DRO</h2>
        <!-- Home All Button -->
        <div class="flex items-center space-x-2">
          <!-- WCS Dropdown -->
          <select 
            v-model="status.g5x_index"
            @change="updateWcs"
            class="bg-gray-900 border border-gray-600 text-gray-200 text-xs rounded px-2 py-1 outline-none font-bold"
            title="Work Coordinate System"
            :disabled="!isMachineOn"
          >
            <option 
              v-for="sys in WORK_COORDINATE_SYSTEMS" 
              :key="sys.index" 
              :value="sys.index"
            >
              {{ sys.name }}
            </option>
          </select>
          <button
            @click="store.homeAll()"
            :disabled="!isMachineOn"
            class="flex items-center space-x-1 px-3 py-1 rounded text-xs font-bold bg-blue-700 hover:bg-blue-600 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            title="Home All Axes"
          >
            <span>⌂</span>
            <span>HOME ALL</span>
          </button>
        </div>
      </div>
      
      <div class="p-6 space-y-4 font-mono text-3xl text-right tracking-tight">
        <!-- X Axis Row -->
        <div class="flex justify-between items-center bg-gray-900 px-4 py-3 rounded border border-gray-800">
          <div class="flex items-center space-x-2">
            <span class="text-red-500 font-bold w-6">X</span>
            <button
              @click="store.homeAxis(0)"
              :disabled="!isMachineOn"
              class="px-2 py-1 rounded text-base bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              title="Home X Axis"
            >🏠</button>
            <button
              @click="openSetPosition(0, 'X', droX)"
              :disabled="!isMachineOn"
              class="px-2 py-1 rounded text-xs font-bold bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              title="Set X Position"
            >SET</button>
          </div>
          <span class="text-gray-100">{{ droX }}</span>
        </div>
        
        <!-- Y Axis Row -->
        <div class="flex justify-between items-center bg-gray-900 px-4 py-3 rounded border border-gray-800">
          <div class="flex items-center space-x-2">
            <span class="text-green-500 font-bold w-6">Y</span>
            <button
              @click="store.homeAxis(1)"
              :disabled="!isMachineOn"
              class="px-2 py-1 rounded text-base bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              title="Home Y Axis"
            >🏠</button>
            <button
              @click="openSetPosition(1, 'Y', droY)"
              :disabled="!isMachineOn"
              class="px-2 py-1 rounded text-xs font-bold bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              title="Set Y Position"
            >SET</button>
          </div>
          <span class="text-gray-100">{{ droY }}</span>
        </div>
        
        <!-- Z Axis Row -->
        <div class="flex justify-between items-center bg-gray-900 px-4 py-3 rounded border border-gray-800">
          <div class="flex items-center space-x-2">
            <span class="text-blue-500 font-bold w-6">Z</span>
            <button
              @click="store.homeAxis(2)"
              :disabled="!isMachineOn"
              class="px-2 py-1 rounded text-base bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              title="Home Z Axis"
            >🏠</button>
            <button
              @click="openSetPosition(2, 'Z', droZ)"
              :disabled="!isMachineOn"
              class="px-2 py-1 rounded text-xs font-bold bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              title="Set Z Position"
            >SET</button>
          </div>
          <span class="text-gray-100">{{ droZ }}</span>
        </div>
      </div>
      
      <div class="bg-gray-700/30 px-4 py-3 flex justify-between text-sm text-gray-400">
        <span>Machine Pos</span>
        <span v-if="status.homed.every(h => h === 1)" class="text-green-400">Homed</span>
        <span v-else class="text-yellow-500">Un-homed</span>
      </div>
    </div>

    <!-- Set Position Modal -->
    <Teleport to="body">
      <div
        v-if="setPositionModal.visible"
        class="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
        @click.self="closeSetPosition"
      >
        <div class="bg-gray-800 border border-gray-600 rounded-lg p-6 shadow-2xl w-72">
          <h3 class="text-lg font-bold text-gray-100 mb-4">Set {{ setPositionModal.axisName }} Position</h3>
          <input
            v-model="setPositionModal.value"
            type="number"
            step="0.001"
            class="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-gray-100 font-mono text-xl text-right focus:outline-none focus:border-blue-500"
            @keyup.enter="applySetPosition"
            @keyup.escape="closeSetPosition"
            autofocus
          />
          <div class="flex space-x-3 mt-4">
            <button
              @click="applySetPosition"
              class="flex-1 bg-blue-600 hover:bg-blue-500 text-white font-bold py-2 rounded transition-colors"
            >Apply</button>
            <button
              @click="closeSetPosition"
              class="flex-1 bg-gray-700 hover:bg-gray-600 text-gray-300 font-bold py-2 rounded transition-colors"
            >Cancel</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
