<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useMachineStore } from '../store.js'

const MAX_JOG_SPEED = 3.602

const machineStore = useMachineStore()
const { jogIntervals } = storeToRefs(machineStore)

const sliderPos = ref(2)
const jogSpeed = computed(() => Math.pow(10, sliderPos.value))

const KEY_BINDINGS = {
  ArrowRight: { axis: 0, direction: 1 },
  ArrowLeft: { axis: 0, direction: -1 },
  ArrowUp: { axis: 1, direction: 1 },
  ArrowDown: { axis: 1, direction: -1 },
  PageUp: { axis: 2, direction: 1 },
  PageDown: { axis: 2, direction: -1 }
}

const isTypingInField = () => {
  const element = document.activeElement
  return Boolean(
    element &&
      (element.tagName === 'INPUT' ||
        element.tagName === 'TEXTAREA' ||
        element.isContentEditable)
  )
}

const startJog = async (axis, direction) => {
  const velocity = direction * jogSpeed.value
  await machineStore.jogContinuous(axis, velocity)
}

const stopJog = async (axis) => {
  await machineStore.jogStop(axis)
}

// ``stopAllJogging`` is critical for safety: when the user
// navigates away or the component is unmounted (including via
// ``v-if``), every in-flight jog must be stopped.  The store
// also tears down its keep-alive intervals in
// ``useMachineStore().disconnect()`` so a hot-reload during a
// jog releases the axis within the watchdog timeout.
const stopAllJogging = async () => {
  const axes = Object.keys(jogIntervals.value).map(Number)
  for (const axis of axes) {
    await machineStore.jogStop(axis)
  }
}

const handleKeyDown = (event) => {
  if (event.repeat || isTypingInField()) {
    return
  }

  const binding = KEY_BINDINGS[event.code]
  if (!binding) {
    return
  }

  event.preventDefault()
  void startJog(binding.axis, binding.direction)
}

const handleKeyUp = (event) => {
  const binding = KEY_BINDINGS[event.code]
  if (!binding) {
    return
  }

  event.preventDefault()
  void stopJog(binding.axis)
}

const handleWindowBlur = () => {
  void stopAllJogging()
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
  window.addEventListener('keyup', handleKeyUp)
  window.addEventListener('blur', handleWindowBlur)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeyDown)
  window.removeEventListener('keyup', handleKeyUp)
  window.removeEventListener('blur', handleWindowBlur)
  void stopAllJogging()
})
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden mt-6">
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex justify-between items-center">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">Jog Controls</h2>
      <span class="text-xs text-gray-400">Hold buttons or arrow keys for continuous motion</span>
    </div>

    <div class="px-4 pt-4">
      <label class="block text-sm font-medium text-gray-300 mb-2">
        Jog Speed: {{ jogSpeed < 10 ? jogSpeed.toFixed(2) : jogSpeed.toFixed(1) }} mm/s
      </label>
      <input
        v-model.number="sliderPos"
        type="range"
        min="-1"
        :max="MAX_JOG_SPEED"
        step="0.001"
        class="w-full h-2 bg-gray-600 rounded-lg appearance-none cursor-pointer"
      />
    </div>

    <div class="p-6 grid grid-cols-3 gap-3 text-center">
      <div class="col-start-2">
        <button
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors touch-none select-none"
          @mousedown.prevent="startJog(1, 1)"
          @touchstart.prevent="startJog(1, 1)"
          @mouseup="stopJog(1)"
          @mouseleave="stopJog(1)"
          @touchend="stopJog(1)"
          @touchcancel="stopJog(1)"
        >Y+ (↑)</button>
      </div>

      <div class="col-start-3">
        <button
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors touch-none select-none"
          @mousedown.prevent="startJog(2, 1)"
          @touchstart.prevent="startJog(2, 1)"
          @mouseup="stopJog(2)"
          @mouseleave="stopJog(2)"
          @touchend="stopJog(2)"
          @touchcancel="stopJog(2)"
        >Z+ (PgUp)</button>
      </div>

      <div class="col-start-1">
        <button
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors touch-none select-none"
          @mousedown.prevent="startJog(0, -1)"
          @touchstart.prevent="startJog(0, -1)"
          @mouseup="stopJog(0)"
          @mouseleave="stopJog(0)"
          @touchend="stopJog(0)"
          @touchcancel="stopJog(0)"
        >X- (←)</button>
      </div>

      <div class="col-start-2 flex items-center justify-center">
        <div class="h-4 w-4 rounded-full bg-gray-600 shadow-inner"></div>
      </div>

      <div class="col-start-3">
        <button
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors touch-none select-none"
          @mousedown.prevent="startJog(0, 1)"
          @touchstart.prevent="startJog(0, 1)"
          @mouseup="stopJog(0)"
          @mouseleave="stopJog(0)"
          @touchend="stopJog(0)"
          @touchcancel="stopJog(0)"
        >X+ (→)</button>
      </div>

      <div class="col-start-2">
        <button
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors touch-none select-none"
          @mousedown.prevent="startJog(1, -1)"
          @touchstart.prevent="startJog(1, -1)"
          @mouseup="stopJog(1)"
          @mouseleave="stopJog(1)"
          @touchend="stopJog(1)"
          @touchcancel="stopJog(1)"
        >Y- (↓)</button>
      </div>

      <div class="col-start-3">
        <button
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors touch-none select-none"
          @mousedown.prevent="startJog(2, -1)"
          @touchstart.prevent="startJog(2, -1)"
          @mouseup="stopJog(2)"
          @mouseleave="stopJog(2)"
          @touchend="stopJog(2)"
          @touchcancel="stopJog(2)"
        >Z- (PgDn)</button>
      </div>
    </div>
  </div>
</template>
