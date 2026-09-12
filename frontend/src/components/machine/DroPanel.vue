<script setup lang="ts">
import {computed, onMounted, ref} from 'vue'
import {storeToRefs} from 'pinia'
import {Axis, useMachineStore} from '../../stores/machine'
import {useBaseThreadStore} from '../../stores/baseThread'
import {WORK_COORDINATE_SYSTEMS} from '../../config/gcodes'
import {useMacroButtonConfig, MacroButton} from '../../ui'
import BaseCard from "../../ui/BaseCard.vue";
import {BaseButton} from "../../ui";
import BaseInput from "../../ui/BaseInput.vue";
import BaseSelect from "../../ui/BaseSelect.vue";

const store = useMachineStore()
const baseThreadStore = useBaseThreadStore()
const {droX, droY, droZ, isMachineOn, status} = storeToRefs(store)
const {axes: baseThreadAxes} = storeToRefs(baseThreadStore)

/**
 * Canonical axis letters (x/y/z) whose joints are all homed.
 * For each canonical letter we look up its ``AxisState`` in the
 * base-thread axes map and check every ``jointNumbers`` entry
 * against ``status.homed`` from the servo thread. Non-canonical
 * entries on the snapshot are simply never visited; when the
 * canonical axes list shrinks back to ``{x, y, z}`` nothing on
 * this side needs to change.
 */
const homedAxisLetters = computed<Set<string>>(() => {
  const axes = baseThreadAxes.value || {}
  const homed = status.value.homed || []
  const out = new Set<string>()
  for (const letter of [Axis.X, Axis.Y, Axis.Z]) {
    const axis = axes[letter]
    if (!axis) continue
    const joints = axis.jointNumbers || []
    if (joints.length === 0) continue
    if (joints.every((j) => Number(homed[j]) === 1)) {
      out.add(letter)
    }
  }
  return out
})

const allAxesHomed = computed(
    () => homedAxisLetters.value.has(Axis.X)
        && homedAxisLetters.value.has(Axis.Y)
        && homedAxisLetters.value.has(Axis.Z),
)

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
const {buttonsBySlot} = buttonConfig

onMounted(() => {
  // Fire-and-forget; the composable handles missing keys by
  // defaulting to ``[]``.
  buttonConfig.refresh()
})

// Set Position modal state
const setPositionModal = ref<{visible: boolean; axis: number | null; axisName: string; value: string}>({visible: false, axis: null, axisName: '', value: ''})

// Speed controls state (initialized to default values)
const speedMultiplier = ref(100) // 100%
const maxSpeed = ref(1000) // mm/min or unit/min

function openSetPosition(axis: number, axisName: string, currentValue: number) {
  setPositionModal.value = {visible: true, axis, axisName, value: String(currentValue)}
}

function closeSetPosition() {
  setPositionModal.value = {visible: false, axis: null, axisName: '', value: ''}
}

async function applySetPosition() {
  const {axis, value} = setPositionModal.value
  if (axis === null) return
  const parsed = parseFloat(value)
  if (!isFinite(parsed)) return
  await store.setPosition(axis, parsed)
  closeSetPosition()
}

function updateWcs(event: Event) {
  const newIndex = parseInt((event.target as HTMLSelectElement).value)
  const system = WORK_COORDINATE_SYSTEMS.find(s => s.index === newIndex)
  if (system) {
    store.setCoordinateSystem(system.name)
  }
}
</script>

<template>
  <!-- DRO (Digital Readout) Panel -->
  <BaseCard title="Toolhead / DRO" footer="Machine Pos">
    <template #header-actions>
      <div class="flex items-center space-x-2">
        <!-- WCS Dropdown -->
        <BaseSelect
            v-model="status.g5xIndex"
            @change="updateWcs"
            class="text-xs"
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
        </BaseSelect>
        <BaseButton
            @click="store.homeAll()"
            :disabled="!isMachineOn"
            size="sm"
            title="Home All Axes"
        >
          <template #icon>
            <span>⌂</span>
          </template>
          <span>HOME ALL</span>
        </BaseButton>
      </div>
    </template>

    <div class="space-y-4 font-mono text-3xl text-right tracking-tight p-4">
      <!-- X Axis Row -->
      <div class="flex justify-between items-center bg-gray-900 px-4 py-3 rounded border border-gray-800">
        <div class="flex items-center space-x-2">
          <span class="text-red-500 font-bold w-6">X</span>
          <BaseButton
              @click="store.homeAxis(Axis.X)"
              :disabled="!isMachineOn"
              variant="secondary"
              size="sm"
              class="text-base"
              title="Home X Axis"
          >
            🏠
          </BaseButton>
          <MacroButton
              :descriptor="buttonsBySlot['dro.x']"
              variant="secondary"
              size="sm"
              class="px-2 py-1 text-xs"
          />
          <BaseButton
              @click="openSetPosition(0, 'X', 0)"
              :disabled="!isMachineOn"
              variant="secondary"
              size="sm"
              title="Set X Position"
          >
            SET
          </BaseButton>
        </div>
        <span :class="homedAxisLetters.has(Axis.X) ? 'text-gray-100' : 'text-gray-600'">
            {{ droX }}
          </span>
      </div>

      <!-- Y Axis Row -->
      <div class="flex justify-between items-center bg-gray-900 px-4 py-3 rounded border border-gray-800">
        <div class="flex items-center space-x-2">
          <span class="text-green-500 font-bold w-6">Y</span>
          <BaseButton
              @click="store.homeAxis(Axis.Y)"
              :disabled="!isMachineOn"
              variant="secondary"
              size="sm"
              class="text-base"
              title="Home Y Axis"
          >
            🏠
          </BaseButton>
          <MacroButton
              :descriptor="buttonsBySlot['dro.y']"
              variant="secondary"
              size="sm"
              class="px-2 py-1 text-xs"
          />
          <BaseButton
              @click="openSetPosition(1, 'Y', 0)"
              :disabled="!isMachineOn"
              variant="secondary"
              size="sm"
              title="Set Y Position"
          >
            SET
          </BaseButton>
        </div>
        <span :class="homedAxisLetters.has(Axis.Y) ? 'text-gray-100' : 'text-gray-600'">
            {{ droY }}
          </span>
      </div>

      <!-- Z Axis Row -->
      <div class="flex justify-between items-center bg-gray-900 px-4 py-3 rounded border border-gray-800">
        <div class="flex items-center space-x-2">
          <span class="text-blue-500 font-bold w-6">Z</span>
          <BaseButton
              @click="store.homeAxis(Axis.Z)"
              :disabled="!isMachineOn"
              variant="secondary"
              size="sm"
              class="text-base"
              title="Home Z Axis"
          >
            🏠
          </BaseButton>
          <MacroButton
              :descriptor="buttonsBySlot['dro.z']"
              variant="secondary"
              size="sm"
              class="px-2 py-1 text-xs"
          />
          <BaseButton
              @click="openSetPosition(2, 'Z', 0)"
              :disabled="!isMachineOn"
              variant="secondary"
              size="sm"
              title="Set Z Position"
          >
            SET
          </BaseButton>
        </div>
        <span :class="homedAxisLetters.has(Axis.Z) ? 'text-gray-100' : 'text-gray-600'">
            {{ droZ }}
          </span>
      </div>
    </div>

    <template #footer-actions>
      <span v-if="allAxesHomed" class="text-green-400">Homed</span>
      <span v-else class="text-yellow-500">Un-homed</span>
    </template>


  </BaseCard>

  <!-- Speed Controls Panel -->


  <!-- Set Position Modal -->
  <Teleport to="body">
    <div
        v-if="setPositionModal.visible"
        class="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
        @click.self="closeSetPosition"
    >
      <div class="bg-gray-800 border border-gray-600 rounded-lg p-6 w-72">
        <h3 class="text-lg font-bold text-gray-100 mb-4">Set {{ setPositionModal.axisName }} Position</h3>
        <BaseInput
            v-model="setPositionModal.value"
            type="number"
            step="0.001"
            class="w-full font-mono text-xl text-right"
            @keyup.enter="applySetPosition"
            @keyup.escape="closeSetPosition"
            autofocus
        />
        <div class="flex space-x-3 mt-4">
          <BaseButton
              @click="applySetPosition"
              variant="primary"
              class="flex-1"
          >
            Apply
          </BaseButton>
          <BaseButton
              @click="closeSetPosition"
              variant="secondary"
              class="flex-1"
          >
            Cancel
          </BaseButton>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style>
/* Range slider styles moved to ``frontend/src/style.css`` —
 * ``@tailwindcss/oxide`` 4.2.4 panics on UTF-8 decoding of these
 * rules inside scoped Vue blocks.
 */
</style>