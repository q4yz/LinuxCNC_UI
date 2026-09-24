<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount, useAttrs } from 'vue'
import { useConsoleStore } from '../stores/console'

const consoleStore = useConsoleStore()

defineOptions({
  inheritAttrs: false
})

const props = defineProps<{
  modelValue: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', newValue: boolean): void
}>()

const attrs = useAttrs()
// Detect if the parent actually provided a v-model or @update:modelValue listener
const hasListener = computed(() => !!attrs['onUpdate:modelValue'])

const isPending = ref(false)
const optimisticValue = ref(false)
const localValue = ref(props.modelValue) // State for unmanaged/transition mode
let timeoutId: number | null = null

// Keep the local fallback synced just in case the parent updates the prop
// statically but doesn't listen for changes.
watch(() => props.modelValue, (newVal) => {
  localValue.value = newVal
})

const currentDisplayValue = computed(() => {
  if (!hasListener.value) return localValue.value
  return isPending.value ? optimisticValue.value : props.modelValue
})

watch(() => props.modelValue, (newBackendState) => {
  if (hasListener.value && isPending.value && newBackendState === optimisticValue.value) {
    consoleStore.success(`new value is set: ${optimisticValue.value}`)
    isPending.value = false
    if (timeoutId) clearTimeout(timeoutId)
  }
})

function warningAndToggleValue() {
  localValue.value = !localValue.value
  consoleStore.warning('Checkbox action not implemented. Toggling locally.')
}

function dispatchOptimisticUpdate() {
  optimisticValue.value = !props.modelValue
  isPending.value = true

  consoleStore.debug(`optimisticValue set to ${optimisticValue.value}`)
  emit('update:modelValue', optimisticValue.value)
}

function handleSyncTimeout() {
  if (isPending.value) {
    isPending.value = false
    consoleStore.error('State synchronization timed out. Machine did not respond.')
  }
}

const toggle = (event: Event) => {
  if (props.disabled || (isPending.value && hasListener.value)) {
    event.preventDefault()
    return
  }

  if (!hasListener.value) {
    warningAndToggleValue();
    return
  }

  dispatchOptimisticUpdate();

  timeoutId = window.setTimeout(() => {
    handleSyncTimeout();
  }, 3000)
}

onBeforeUnmount(() => {
  if (timeoutId) clearTimeout(timeoutId)
})
</script>

<template>
  <div class="relative flex items-center m-2">
    <input
      type="checkbox"
      :checked="currentDisplayValue"
      :disabled="disabled || (isPending && hasListener)"
      @click.prevent="toggle"
      v-bind="$attrs"
      class="w-6 h-6 text-blue-500 bg-gray-900 border-gray-700 rounded cursor-pointer appearance-none checked:bg-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-800 transition-all duration-200 flex items-center justify-center"
      :class="{
        'opacity-50 animate-pulse cursor-wait': isPending && hasListener,
        'cursor-not-allowed opacity-50': disabled && (!isPending || !hasListener)
      }"
    />

    <svg
      v-if="currentDisplayValue"
      class="absolute w-4 h-4 text-white pointer-events-none left-1"
      :class="{ 'opacity-50': isPending && hasListener }"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      stroke-width="3"
    >
      <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  </div>
</template>