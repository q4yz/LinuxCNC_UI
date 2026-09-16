<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue'

defineOptions({
  inheritAttrs: false
})

// The true state coming from the backend
const props = defineProps<{
  modelValue: boolean
  disabled?: boolean
}>()

// Emits the change request and any timeout errors
const emit = defineEmits(['update:modelValue', 'error'])

const isPending = ref(false)
const optimisticValue = ref(false)
let timeoutId: number | null = null

// The checkbox displays our optimistic guess if pending, otherwise the true backend state
const currentDisplayValue = computed(() => {
  return isPending.value ? optimisticValue.value : props.modelValue
})

// Watch the true backend state for confirmation
watch(() => props.modelValue, (newBackendState) => {
  if (isPending.value && newBackendState === optimisticValue.value) {
    // The backend confirmed our change! Clear the pending state and timer.
    isPending.value = false
    if (timeoutId) clearTimeout(timeoutId)
  }
})

const toggle = (event: Event) => {
  // Prevent spam-clicking while waiting for the backend
  if (props.disabled || isPending.value) {
    event.preventDefault()
    return
  }

  // Set the optimistic state and mark as pending
  optimisticValue.value = !props.modelValue
  isPending.value = true

  // Tell the parent component to send the API request
  emit('update:modelValue', optimisticValue.value)

  // Start the 3-second rollback timer
  timeoutId = window.setTimeout(() => {
    if (isPending.value) {
      // The backend never confirmed. Roll back the visual state.
      isPending.value = false
      emit('error', 'State synchronization timed out. Machine did not respond.')
    }
  }, 3000)
}

// Clean up the timer if the component is destroyed before the 3 seconds are up
onBeforeUnmount(() => {
  if (timeoutId) clearTimeout(timeoutId)
})
</script>

<template>
  <div class="relative flex items-center m-2">
    <input
      type="checkbox"
      :checked="currentDisplayValue"
      :disabled="disabled || isPending"
      @click.prevent="toggle"
      v-bind="$attrs"
      class="w-6 h-6 text-blue-500 bg-gray-900 border-gray-700 rounded cursor-pointer appearance-none checked:bg-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-800 transition-all duration-200 flex items-center justify-center"
      :class="{
        'opacity-50 animate-pulse cursor-wait': isPending,
        'cursor-not-allowed opacity-50': disabled && !isPending
      }"
    />

    <!-- Custom SVG Checkmark to overlay on the appearance-none input -->
    <svg
      v-if="currentDisplayValue"
      class="absolute w-4 h-4 text-white pointer-events-none left-1"
      :class="{ 'opacity-50': isPending }"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      stroke-width="3"
    >
      <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  </div>
</template>