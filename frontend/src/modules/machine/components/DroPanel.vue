<script setup>
import { onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useMachineStore } from '../store'
import { WORK_COORDINATE_SYSTEMS } from '../../../config/gcodes'
import { useMacroButtonConfig, MacroButton } from '../../../ui'

const store = useMachineStore()
const { droX, droY, droZ, isEstop, isMachineOn, machineStateText, status } = storeToRefs(store)

// Custom macro buttons (one slot per axis row). The shared
// ``useMacroButtonConfig`` composable reads from the per-module
// ``SettingsStore``; ``buttonsBySlot`` is a slot id → descriptor
// lookup. ``MacroButton`` renders nothing when the matching row
// is missing, disabled, or empty.
//
// The settings moduleId is ``"axis"`` (not ``manifest.id`` of
// ``"machine"``) to match the backend's ``_MODULE_DOMAINS[0]``
// mount under that id; the write surface
// (``MachineSettingsPanel.vue``) uses the same id so both ends
// of the read/write pair share ``<data_root>/modules/axis/settings.json``.
const buttonConfig = useMacroButtonConfig('axis')
const { buttonsBySlot } = buttonConfig

onMounted(() => {
  // Fire-and-forget; the composable handles missing keys by
  // defaulting to ``[]``.
  buttonConfig.refresh()
})

// Set Position modal state
const setPositionModal = ref({ visible: false, axis: null, axisName: '', value: '' })

// Speed controls state (initialized to default values)
const speedMultiplier = ref(100) // 100%
const maxSpeed = ref(1000) // mm/min or unit/min

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

async function handleSpeedMultiplierChange() {
  await store.updateAxisSettings(speedMultiplier.value / 100, maxSpeed.value)
}

async function handleMaxSpeedChange() {
  await store.updateAxisSettings(speedMultiplier.value / 100, maxSpeed.value)
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
            <MacroButton
                :descriptor="buttonsBySlot['dro.x']"
                variant="secondary"
                size="sm"
                class="px-2 py-1 text-xs"
            />
            <button
                @click="openSetPosition(0, 'X', 0)"
                :disabled="!isMachineOn"
                class="px-2 py-1 rounded text-xs font-bold bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                title="Set X Position"
            >SET</button>
          </div>
          <span :class="status.homed && status.homed[0] ? 'text-gray-100' : 'text-gray-600'">
            {{ droX }}
          </span>
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
            <MacroButton
                :descriptor="buttonsBySlot['dro.y']"
                variant="secondary"
                size="sm"
                class="px-2 py-1 text-xs"
            />
            <button
                @click="openSetPosition(1, 'Y', 0)"
                :disabled="!isMachineOn"
                class="px-2 py-1 rounded text-xs font-bold bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                title="Set Y Position"
            >SET</button>
          </div>
          <span :class="status.homed && status.homed[1] ? 'text-gray-100' : 'text-gray-600'">
            {{ droY }}
          </span>
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
            <MacroButton
                :descriptor="buttonsBySlot['dro.z']"
                variant="secondary"
                size="sm"
                class="px-2 py-1 text-xs"
            />
            <button
                @click="openSetPosition(2, 'Z', 0)"
                :disabled="!isMachineOn"
                class="px-2 py-1 rounded text-xs font-bold bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                title="Set Z Position"
            >SET</button>
          </div>
          <span :class="status.homed && status.homed[2] ? 'text-gray-100' : 'text-gray-600'">
            {{ droZ }}
          </span>
        </div>
      </div>

      <div class="bg-gray-700/30 px-4 py-3 flex justify-between text-sm text-gray-400">
        <span>Machine Pos</span>
        <span v-if="status.homed && status.homed.every(h => h === 1)" class="text-green-400">Homed</span>
        <span v-else class="text-yellow-500">Un-homed</span>
      </div>
    </div>

    <!-- Speed Controls Panel -->
    <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl p-6 space-y-6">
      <!-- Speed Multiplier (Feed Override) -->
      <div>
        <div class="flex justify-between items-end mb-2">
          <label class="text-sm font-semibold text-gray-300 uppercase tracking-wider">Speed Multiplier</label>
          <span class="font-mono text-lg text-blue-400 font-bold">{{ speedMultiplier }}%</span>
        </div>
        <input
            type="range"
            v-model="speedMultiplier"
            @change="handleSpeedMultiplierChange"
            min="0"
            max="200"
            step="1"
            class="w-full h-2 bg-gray-900 rounded-lg appearance-none cursor-pointer accent-blue-500 focus:outline-none"
            :disabled="!isMachineOn"
        >
      </div>

      <!-- Max Speed (Absolute) -->
      <div>
        <div class="flex justify-between items-end mb-2">
          <label class="text-sm font-semibold text-gray-300 uppercase tracking-wider">Max Speed</label>
          <span class="font-mono text-lg text-blue-400 font-bold">{{ maxSpeed }} mm/min</span>
        </div>
        <input
            type="range"
            v-model="maxSpeed"
            @change="handleMaxSpeedChange"
            min="0"
            max="5000"
            step="10"
            class="w-full h-2 bg-gray-900 rounded-lg appearance-none cursor-pointer accent-blue-500 focus:outline-none"
            :disabled="!isMachineOn"
        >
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

<style scoped>
/* Cross-browser styling for the range sliders */
input[type=range]::-webkit-slider-thumb {
  appearance: none;
  width: 20px;
  height: 20px;
  background: #3b82f6; /* Tailwind blue-500 */
  border-radius: 50%;
  cursor: pointer;
}
input[type=range]::-moz-range-thumb {
  width: 20px;
  height: 20px;
  background: #3b82f6;
  border: none;
  border-radius: 50%;
  cursor: pointer;
}
input[type=range]:disabled::-webkit-slider-thumb {
  background: #4b5563; /* Tailwind gray-600 */
  cursor: not-allowed;
}
input[type=range]:disabled::-moz-range-thumb {
  background: #4b5563;
  cursor: not-allowed;
}
</style>