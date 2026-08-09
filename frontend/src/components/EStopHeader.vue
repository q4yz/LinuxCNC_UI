<script setup>
import { storeToRefs } from 'pinia'
import { useMachineStore } from '../stores/machine-compat.js'

const store = useMachineStore()
// Re-importing isEstop so we can reactively change the button's visual state
const { isEstop } = storeToRefs(store)

async function pressEStop() {
  await store.toggleEstop()
}
</script>

<template>
  <!--
    The gray container box anchors the button to the top-right corner.
    rounded-bl-xl gives it a control-panel look rather than just floating.
  -->
  <div class="fixed top-0 right-0 z-[100] bg-gray-800 p-3 sm:p-4 shadow-xl border-b border-l border-gray-700 rounded-bl-xl">

    <!--
      The button is now square (w-20 h-20) with slightly rounded corners (rounded-md).
      We use dynamic classes to switch between the "Normal" and "Pressed" states.
    -->
    <button
      type="button"
      :class="[
        'flex items-center justify-center w-20 h-20 sm:w-24 sm:h-12',
        'text-white font-extrabold uppercase tracking-widest text-xl',
        'border-4 rounded-md transition-all focus:outline-none',
        isEstop
          ? 'bg-red-900 border-black shadow-inner scale-95 translate-y-1' // Darker, pushed-in look
          : 'bg-red-600 hover:bg-red-500 active:bg-red-800 border-red-900 shadow-lg' // Bright, popped-out look
      ]"
      :aria-pressed="isEstop"
      aria-label="Emergency Stop"
      title="Emergency Stop"
      data-testid="estop-button"
      @click="pressEStop"
    >
      STOP
    </button>
  </div>
</template>