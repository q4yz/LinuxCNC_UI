<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useMachineStore } from '../../stores/machine'

const MAX_JOG_SPEED = 3.602

const machineStore = useMachineStore()
const { defaultJogVelocity } = storeToRefs(machineStore)

// Locally tracked axes that currently have an active continuous jog.
const activeJogAxes = ref(new Set())

// Key ledger to ensure a window blur doesn't orphan a keyup event.
const keysHeldForJog = ref(new Set())

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
  // Standard Arrow Keys
  ArrowRight: { axis: 0, direction: 1 },
  ArrowLeft: { axis: 0, direction: -1 },
  ArrowUp: { axis: 1, direction: 1 },
  ArrowDown: { axis: 1, direction: -1 },
  PageUp: { axis: 2, direction: 1 },
  PageDown: { axis: 2, direction: -1 },

  // Numpad Keys (NumLock ON)
  Numpad6: { axis: 0, direction: 1 },   // Right
  Numpad4: { axis: 0, direction: -1 },  // Left
  Numpad8: { axis: 1, direction: 1 },   // Back (Up)
  Numpad2: { axis: 1, direction: -1 },  // Forward (Down)
  Numpad9: { axis: 2, direction: 1 },   // Z-Up
  Numpad3: { axis: 2, direction: -1 }   // Z-Down
}

// All keys that can cause a browser scroll. We aggressively preventDefault
// on these so the page doesn't jump around while jogging.
const SCROLL_KEYS = [
  'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
  'PageUp', 'PageDown', 'Space', 'Home', 'End',
  'Numpad8', 'Numpad2', 'Numpad4', 'Numpad6', 'Numpad9', 'Numpad3'
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
  const axes = Array.from(activeJogAxes.value)
  activeJogAxes.value.clear()
  keysHeldForJog.value.clear()
  for (const axis of axes) {
    await machineStore.jogStop(axis)
  }
}

const handleKeyDown = (event) => {
  if (isTypingInField()) return

  // 1. Activate Panel via Numpad 5
  if (event.code === 'Numpad5') {
    event.preventDefault()
    containerRef.value?.focus()
    activate()
    return
  }

  // If the panel isn't focused/active, ignore all other inputs
  if (!isActive.value) return

  // 2. Adjust Speed via +/- (Numpad or standard keys)
  if (event.code === 'NumpadAdd' || event.key === '+') {
    event.preventDefault()
    sliderTouched.value = true
    sliderPos.value = Math.min(MAX_JOG_SPEED, sliderPos.value + 0.1)
    return
  }
  if (event.code === 'NumpadSubtract' || event.key === '-') {
    event.preventDefault()
    sliderTouched.value = true
    sliderPos.value = Math.max(-1, sliderPos.value - 0.1)
    return
  }

  // 3. Prevent page scrolling for navigation keys
  if (SCROLL_KEYS.includes(event.code)) {
    event.preventDefault()
  }

  if (event.repeat) return

  // 4. Dispatch the Jog Command
  const binding = KEY_BINDINGS[event.code]
  if (!binding) return

  event.preventDefault()
  keysHeldForJog.value.add(event.code)
  void startJog(binding.axis, binding.direction)
}

const handleKeyUp = (event) => {
  if (!keysHeldForJog.value.has(event.code)) return
  keysHeldForJog.value.delete(event.code)

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
  isActive.value = false
  void stopAllJogging()
  keysHeldForJog.value.clear()
})
</script>

<template>
  <div
      ref="containerRef"
      tabindex="0"
      @focusin="activate"
      @focusout="handleFocusOut"
      class="bg-gray-800 rounded-lg shadow-xl overflow-hidden outline-none transition-all duration-200 border"
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
      <span class="text-xs text-gray-400">Hold Numpad (8/2/4/6/9/3) or Arrows</span>
    </div>

    <div class="px-4 pt-4">
      <div class="flex justify-between items-end mb-2">
        <label class="block text-sm font-medium text-gray-300">
          Jog Speed: <span class="font-mono text-blue-300">{{ jogSpeed < 10 ? jogSpeed.toFixed(2) : jogSpeed.toFixed(1) }} mm/s</span>
        </label>
        <span class="text-[10px] text-gray-500">Use +/- to scale</span>
      </div>
      <input
          v-model.number="sliderPos"
          @input="sliderTouched = true"
          type="range"
          min="-1"
          :max="MAX_JOG_SPEED"
          step="0.001"
          tabindex="-1"
          class="w-full h-2 bg-gray-600 rounded-lg appearance-none cursor-pointer focus:outline-none"
      />
    </div>

    <div class="p-6 grid grid-cols-3 gap-3 text-center">
      <div class="col-start-2">
        <button
            class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-all select-none focus:outline-none"
            :class="isActive ? 'touch-none' : 'opacity-30 pointer-events-none'"
            @pointerdown.prevent="startJog(1, 1)"
            @pointerup="stopJog(1)"
            @pointercancel="stopJog(1)"
            @contextmenu.prevent
        >Y+</button>
      </div>

      <div class="col-start-3">
        <button
            class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-all select-none focus:outline-none"
            :class="isActive ? 'touch-none' : 'opacity-30 pointer-events-none'"
            @pointerdown.prevent="startJog(2, 1)"
            @pointerup="stopJog(2)"
            @pointercancel="stopJog(2)"
            @contextmenu.prevent
        >Z+</button>
      </div>

      <div class="col-start-1">
        <button
            class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-all select-none focus:outline-none"
            :class="isActive ? 'touch-none' : 'opacity-30 pointer-events-none'"
            @pointerdown.prevent="startJog(0, -1)"
            @pointerup="stopJog(0)"
            @pointercancel="stopJog(0)"
            @contextmenu.prevent
        >X-</button>
      </div>

      <div class="col-start-2 flex flex-col items-center justify-center text-[10px] text-gray-500 font-bold uppercase tracking-widest cursor-pointer" @click="() => { containerRef?.focus(); activate(); }">
        <div class="h-4 w-4 rounded-full shadow-inner transition-colors duration-200 mb-1" :class="isActive ? 'bg-blue-500' : 'bg-gray-600'"></div>
        Numpad 5
      </div>

      <div class="col-start-3">
        <button
            class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-all select-none focus:outline-none"
            :class="isActive ? 'touch-none' : 'opacity-30 pointer-events-none'"
            @pointerdown.prevent="startJog(0, 1)"
            @pointerup="stopJog(0)"
            @pointercancel="stopJog(0)"
            @contextmenu.prevent
        >X+</button>
      </div>

      <div class="col-start-2">
        <button
            class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-all select-none focus:outline-none"
            :class="isActive ? 'touch-none' : 'opacity-30 pointer-events-none'"
            @pointerdown.prevent="startJog(1, -1)"
            @pointerup="stopJog(1)"
            @pointercancel="stopJog(1)"
            @contextmenu.prevent
        >Y-</button>
      </div>

      <div class="col-start-3">
        <button
            class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-all select-none focus:outline-none"
            :class="isActive ? 'touch-none' : 'opacity-30 pointer-events-none'"
            @pointerdown.prevent="startJog(2, -1)"
            @pointerup="stopJog(2)"
            @pointercancel="stopJog(2)"
            @contextmenu.prevent
        >Z-</button>
      </div>
    </div>
  </div>
</template>