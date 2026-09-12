<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { storeToRefs } from 'pinia'
import { useMachineStore } from '../../stores/machine'
import BaseRange from "../../ui/BaseRange.vue";
import {BaseButton} from "../../ui/index.ts";
import BaseCard from "../../ui/BaseCard.vue";


const MAX_JOG_SPEED = 3.402

const machineStore = useMachineStore()
const { defaultJogVelocity } = storeToRefs(machineStore)

// Locally tracked axes that currently have an active continuous jog.
const activeJogAxes = ref(new Set<number>())

// Key ledger to ensure a window blur doesn't orphan a keyup event.
const keysHeldForJog = ref(new Set<string>())

const sliderPos = ref(2)
const sliderTouched = ref(false)
watch(defaultJogVelocity, (velocity) => {
  if (sliderTouched.value || !Number.isFinite(velocity) || velocity <= 0) return
  sliderPos.value = Math.min(MAX_JOG_SPEED, Math.max(-1, Math.log10(velocity)))
}, { immediate: true })
const jogSpeed = computed(() => Math.pow(10, sliderPos.value))

const containerRef = ref<ComponentPublicInstance | null>(null)
const isActive = ref(false)

// The card is a component instance; the focusable element lives on ``$el``.
const focusEl = (): HTMLElement | null => {
  const inst = containerRef.value
  if (!inst) return null
  return (inst.$el as HTMLElement | undefined) ?? null
}

const KEY_BINDINGS: Record<string, { axis: number; direction: number }> = {
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
  const element = document.activeElement as HTMLElement | null
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

const focusAndActivate = () => {
  focusEl()?.focus()
  activate()
}

const deactivate = () => {
  if (isActive.value) {
    isActive.value = false
    void stopAllJogging()
  }
}

const handleFocusOut = (event: FocusEvent) => {
  const el = focusEl()
  if (el && !el.contains(event.relatedTarget as Node | null)) {
    deactivate()
  }
}

const startJog = async (axis: number, direction: number) => {
  const velocity = direction * jogSpeed.value
  activeJogAxes.value.add(axis)
  await machineStore.jogContinuous(axis, velocity)
}

const stopJog = async (axis: number) => {
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

const handleKeyDown = (event: KeyboardEvent) => {
  if (isTypingInField()) return

  // 1. Activate Panel via Numpad 5
  if (event.code === 'Numpad5') {
    event.preventDefault()
    focusEl()?.focus()
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

const handleKeyUp = (event: KeyboardEvent) => {
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
  <BaseCard
      ref="containerRef"
      tabindex="0"
      @focusin="activate"
      @focusout="handleFocusOut"
      class="outline-none transition-all duration-200"
      :class="isActive ? '!border-blue-400 ring-2 ring-blue-400/30' : ''"
      title = "Jog Controls"
  >
    <!-- Custom Header mapped to Active State -->

    <template #header-actions :class="isActive ? 'bg-blue-900/40' : 'bg-gray-700/50'">
      <span v-if="isActive" class="ml-3 px-2 py-0.5 rounded text-[10px] bg-blue-500/20 text-blue-300 border border-blue-500/30">Active</span>
      <span class="text-xs text-gray-400">Hold Numpad (8/2/4/6/9/3) or Arrows</span>
    </template>


    <!-- Speed Slider -->
    <div class="px-4 pt-4">
      <div class="flex justify-between items-end mb-2">
        <label class="block text-sm font-medium text-gray-300">
          Jog Speed: <span class="font-mono text-blue-300">{{ jogSpeed < 10 ? jogSpeed.toFixed(2) : jogSpeed.toFixed(1) }} mm/s</span>
        </label>
        <span class="text-[10px] text-gray-500">Use +/- to scale</span>
      </div>
      <BaseRange
          v-model="sliderPos"
          @touched="sliderTouched = true"
          min="0.5"
          :max="MAX_JOG_SPEED"
          step="0.01"
          tabindex="-1"
      />
    </div>

    <!-- Jog Direction Buttons -->
    <div class="p-3 grid grid-cols-3 gap-3 text-center">
      <div class="col-start-2">
        <BaseButton
            variant="secondary"
            size="lg"
            class="w-full text-lg select-none active:bg-blue-600 active:border-blue-600 active:text-white touch-none"
            :disabled="!isActive"
            @pointerdown.prevent="startJog(1, 1)"
            @pointerup="stopJog(1)"
            @pointercancel="stopJog(1)"
            @contextmenu.prevent
        >
          Y+
        </BaseButton>
      </div>

      <div class="col-start-3">
        <BaseButton
            variant="secondary"
            size="lg"
            class="w-full text-lg select-none active:bg-blue-600 active:border-blue-600 active:text-white touch-none"
            :disabled="!isActive"
            @pointerdown.prevent="startJog(2, 1)"
            @pointerup="stopJog(2)"
            @pointercancel="stopJog(2)"
            @contextmenu.prevent
        >
          Z+
        </BaseButton>
      </div>

      <div class="col-start-1">
        <BaseButton
            variant="secondary"
            size="lg"
            class="w-full text-lg select-none active:bg-blue-600 active:border-blue-600 active:text-white touch-none"
            :disabled="!isActive"
            @pointerdown.prevent="startJog(0, -1)"
            @pointerup="stopJog(0)"
            @pointercancel="stopJog(0)"
            @contextmenu.prevent
        >
          X-
        </BaseButton>
      </div>

      <!-- Center Numpad Indicator -->
      <div
          class="col-start-2 flex flex-col items-center justify-center text-[10px] text-gray-500 font-bold uppercase tracking-widest cursor-pointer"
          @click="focusAndActivate"
      >
        <div class="h-4 w-4 rounded-full transition-colors duration-200 mb-1" :class="isActive ? 'bg-blue-500' : 'bg-gray-600'"></div>
        Numpad 5
      </div>

      <div class="col-start-3">
        <BaseButton
            variant="secondary"
            size="lg"
            class="w-full text-lg select-none active:bg-blue-600 active:border-blue-600 active:text-white touch-none"
            :disabled="!isActive"
            @pointerdown.prevent="startJog(0, 1)"
            @pointerup="stopJog(0)"
            @pointercancel="stopJog(0)"
            @contextmenu.prevent
        >
          X+
        </BaseButton>
      </div>

      <div class="col-start-2">
        <BaseButton
            variant="secondary"
            size="lg"
            class="w-full text-lg select-none active:bg-blue-600 active:border-blue-600 active:text-white touch-none"
            :disabled="!isActive"
            @pointerdown.prevent="startJog(1, -1)"
            @pointerup="stopJog(1)"
            @pointercancel="stopJog(1)"
            @contextmenu.prevent
        >
          Y-
        </BaseButton>
      </div>

      <div class="col-start-3">
        <BaseButton
            variant="secondary"
            size="lg"
            class="w-full text-lg select-none active:bg-blue-600 active:border-blue-600 active:text-white touch-none"
            :disabled="!isActive"
            @pointerdown.prevent="startJog(2, -1)"
            @pointerup="stopJog(2)"
            @pointercancel="stopJog(2)"
            @contextmenu.prevent
        >
          Z-
        </BaseButton>
      </div>
    </div>
  </BaseCard>
</template>