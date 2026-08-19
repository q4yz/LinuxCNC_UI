<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useMachineStore } from '../store'

const MAX_JOG_SPEED = 3.602

const machineStore = useMachineStore()
const { defaultJogVelocity } = storeToRefs(machineStore)

// Locally tracked axes that currently have an active continuous jog.
// The keep-alive timers themselves live inside ``servoThreadService``;
// we only need to know *which* axes are moving so we can stop them
// when the panel loses focus / unmounts.
const activeJogAxes = ref(new Set())

const sliderPos = ref(2)
const sliderTouched = ref(false)
watch(defaultJogVelocity, (velocity) => {
  if (sliderTouched.value || !Number.isFinite(velocity) || velocity <= 0) return
  sliderPos.value = Math.min(MAX_JOG_SPEED, Math.max(-1, Math.log10(velocity)))
}, { immediate: true })
const jogSpeed = computed(() => Math.pow(10, sliderPos.value))

const containerRef = ref(null)
const isActive = ref(false)

const KEY_BINDINGS = {
  ArrowRight: { axis: 0, direction: 1 },
  ArrowLeft: { axis: 0, direction: -1 },
  ArrowUp: { axis: 1, direction: 1 },
  ArrowDown: { axis: 1, direction: -1 },
  PageUp: { axis: 2, direction: 1 },
  PageDown: { axis: 2, direction: -1 }
}

// All keys that can cause a browser scroll (used to keep the page
// from scrolling while jogging).
const SCROLL_KEYS = [
  'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
  'PageUp', 'PageDown', 'Space', 'Home', 'End'
]

const isTypingInField = () => {
  const element = document.activeElement
  return Boolean(
    element &&
      (element.tagName === 'INPUT' ||
        element.tagName === 'TEXTAREA' ||
        element.isContentEditable)
  )
}

const blockScroll = (e) => {
  // Allow touch dragging on the speed slider, block everything else.
  if (e.type === 'touchmove' && e.target.tagName === 'INPUT') return
  e.preventDefault()
}

const activate = () => {
  if (!isActive.value) {
    isActive.value = true
  }
}

const deactivate = () => {
  if (isActive.value) {
    isActive.value = false
    void stopAllJogging()
  }
}

const handleFocusOut = (event) => {
  if (containerRef.value && !containerRef.value.contains(event.relatedTarget)) {
    deactivate()
  }
}

const startJog = async (axis, direction) => {
  const velocity = direction * jogSpeed.value
  activeJogAxes.value.add(axis)
  await machineStore.jogContinuous(axis, velocity)
}

const stopJog = async (axis) => {
  activeJogAxes.value.delete(axis)
  await machineStore.jogStop(axis)
}

const stopAllJogging = async () => {
  // Snapshot the keys first — ``jogStop`` mutates the set.
  const axes = Array.from(activeJogAxes.value)
  activeJogAxes.value.clear()
  for (const axis of axes) {
    await machineStore.jogStop(axis)
  }
}

const handleKeyDown = (event) => {
  if (!isActive.value || isTypingInField()) return

  // Aggressively prevent default for ANY key that might scroll the page
  if (SCROLL_KEYS.includes(event.code)) {
    event.preventDefault()
  }

  if (event.repeat) return

  const binding = KEY_BINDINGS[event.code]
  if (!binding) return

  void startJog(binding.axis, binding.direction)
}

const handleKeyUp = (event) => {
  if (!isActive.value) return

  const binding = KEY_BINDINGS[event.code]
  if (!binding) return

  event.preventDefault()
  void stopJog(binding.axis)
}

const handleWindowBlur = () => {
  deactivate()
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
  // Do not rely on focus state here: a component can be destroyed
  // while a jog request is still in flight or after focus moved away.
  isActive.value = false
  void stopAllJogging()
})
</script>

<template>
  <div
    ref="containerRef"
    tabindex="0"
    @focusin="activate"
    @focusout="handleFocusOut"
    class="bg-gray-800 rounded-lg shadow-xl overflow-hidden mt-6 outline-none transition-all duration-200 border"
    :class="isActive ? 'border-blue-400 ring-2 ring-blue-400/30' : 'border-gray-700'"
  >
    <div
      class="px-4 py-3 border-b border-gray-600 flex justify-between items-center transition-colors duration-200"
      :class="isActive ? 'bg-blue-900/40' : 'bg-gray-700/50'"
    >
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        Jog Controls
        <span v-if="isActive" class="ml-3 px-2 py-0.5 rounded text-[10px] bg-blue-500/20 text-blue-300 border border-blue-500/30">Active</span>
      </h2>
      <span class="text-xs text-gray-400">Hold buttons or arrow keys for continuous motion</span>
    </div>

    <div class="px-4 pt-4">
      <label class="block text-sm font-medium text-gray-300 mb-2">
        Jog Speed: {{ jogSpeed < 10 ? jogSpeed.toFixed(2) : jogSpeed.toFixed(1) }} mm/s
      </label>
      <input
        v-model.number="sliderPos"
        @input="sliderTouched = true"
        type="range"
        min="-1"
        :max="MAX_JOG_SPEED"
        step="0.001"
        class="w-full h-2 bg-gray-600 rounded-lg appearance-none cursor-pointer focus:outline-none"
      />
    </div>

    <div class="p-6 grid grid-cols-3 gap-3 text-center">
      <div class="col-start-2">
        <button
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors touch-none select-none focus:outline-none"
          @mousedown.prevent="startJog(1, 1)"
          @touchstart.prevent="startJog(1, 1)"
          @mouseup="stopJog(1)"
          @mouseleave="stopJog(1)"
          @touchend="stopJog(1)"
          @touchcancel="stopJog(1)"
        >Y+</button>
      </div>

      <div class="col-start-3">
        <button
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors touch-none select-none focus:outline-none"
          @mousedown.prevent="startJog(2, 1)"
          @touchstart.prevent="startJog(2, 1)"
          @mouseup="stopJog(2)"
          @mouseleave="stopJog(2)"
          @touchend="stopJog(2)"
          @touchcancel="stopJog(2)"
        >Z+</button>
      </div>

      <div class="col-start-1">
        <button
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors touch-none select-none focus:outline-none"
          @mousedown.prevent="startJog(0, -1)"
          @touchstart.prevent="startJog(0, -1)"
          @mouseup="stopJog(0)"
          @mouseleave="stopJog(0)"
          @touchend="stopJog(0)"
          @touchcancel="stopJog(0)"
        >X-</button>
      </div>

      <div class="col-start-2 flex items-center justify-center">
        <div class="h-4 w-4 rounded-full shadow-inner transition-colors duration-200" :class="isActive ? 'bg-blue-500' : 'bg-gray-600'"></div>
      </div>

      <div class="col-start-3">
        <button
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors touch-none select-none focus:outline-none"
          @mousedown.prevent="startJog(0, 1)"
          @touchstart.prevent="startJog(0, 1)"
          @mouseup="stopJog(0)"
          @mouseleave="stopJog(0)"
          @touchend="stopJog(0)"
          @touchcancel="stopJog(0)"
        >X+</button>
      </div>

      <div class="col-start-2">
        <button
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors touch-none select-none focus:outline-none"
          @mousedown.prevent="startJog(1, -1)"
          @touchstart.prevent="startJog(1, -1)"
          @mouseup="stopJog(1)"
          @mouseleave="stopJog(1)"
          @touchend="stopJog(1)"
          @touchcancel="stopJog(1)"
        >Y-</button>
      </div>

      <div class="col-start-3">
        <button
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors touch-none select-none focus:outline-none"
          @mousedown.prevent="startJog(2, -1)"
          @touchstart.prevent="startJog(2, -1)"
          @mouseup="stopJog(2)"
          @mouseleave="stopJog(2)"
          @touchend="stopJog(2)"
          @touchcancel="stopJog(2)"
        >Z-</button>
      </div>
    </div>
  </div>
</template>
