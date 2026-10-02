<script setup lang="ts">
import { computed } from 'vue'
import { useBackendSync, DEFAULT_SYNC_TIMEOUT_MS } from './useBackendSync'

defineOptions({
  inheritAttrs: false
})

const props = withDefaults(defineProps<{
  // Backend value. ``null`` = not received yet; never defaulted.
  modelValue: boolean | null
  // Operator-facing name, used in every sync log line.
  label: string
  disabled?: boolean
  syncTimeout?: number
  // Declared as a prop (not only an emit) so we can detect whether the
  // parent is listening — declared emit listeners never reach ``$attrs``.
  'onUpdate:modelValue'?: (newValue: boolean) => void
}>(), {
  disabled: false,
  syncTimeout: DEFAULT_SYNC_TIMEOUT_MS,
})

const emit = defineEmits<{
  (e: 'update:modelValue', newValue: boolean): void
}>()

const { displayValue, isPending, isSynced, commit } = useBackendSync<boolean>({
  label: () => props.label,
  source: () => props.modelValue,
  hasListener: () => !!props['onUpdate:modelValue'],
  emit: (value) => emit('update:modelValue', value),
  timeoutMs: () => props.syncTimeout,
})

const isChecked = computed(() => displayValue.value === true)

const toggle = (event: Event) => {
  event.preventDefault()
  if (props.disabled || isPending.value) return
  commit(!isChecked.value)
}
</script>

<template>
  <div class="relative flex items-center m-2">
    <input
      type="checkbox"
      :checked="isChecked"
      :indeterminate="displayValue === null"
      :title="isSynced ? undefined : `${label}: waiting for backend value`"
      v-bind="$attrs"
      :disabled="disabled || isPending"
      :aria-busy="isPending"
      @click="toggle"
      class="w-6 h-6 text-blue-500 bg-gray-900 border-gray-700 rounded cursor-pointer appearance-none checked:bg-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-800 transition-all duration-200 flex items-center justify-center"
      :class="{
        'opacity-50 animate-pulse cursor-wait': isPending,
        'cursor-not-allowed opacity-50': disabled && !isPending,
        'border-dashed border-2 border-gray-500': displayValue === null
      }"
    />

    <svg
      v-if="isChecked"
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
