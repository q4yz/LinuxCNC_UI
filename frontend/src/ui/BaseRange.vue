<script setup lang="ts">
import { computed, ref } from 'vue'
import { useBackendSync, DEFAULT_SYNC_TIMEOUT_MS } from './useBackendSync'

// Disable automatic attribute fallthrough so we can target the input directly
defineOptions({
  inheritAttrs: false
})

const props = withDefaults(defineProps<{
  // Backend value. ``null`` = not received yet; never defaulted.
  modelValue: number | null
  // Operator-facing name, used in every sync log line.
  label: string
  disabled?: boolean
  // Max |requested - echoed| still counted as a confirmation
  // (backends round, e.g. mm/min -> units/s -> mm/min).
  tolerance?: number
  syncTimeout?: number
  // Declared as a prop so we can detect whether the parent is listening.
  'onUpdate:modelValue'?: (newValue: number) => void
}>(), {
  disabled: false,
  tolerance: 1e-6,
  syncTimeout: DEFAULT_SYNC_TIMEOUT_MS,
})

const emit = defineEmits<{
  (e: 'update:modelValue', newValue: number): void
}>()

const { displayValue, isPending, isSynced, commit } = useBackendSync<number>({
  label: () => props.label,
  source: () => props.modelValue,
  hasListener: () => !!props['onUpdate:modelValue'],
  emit: (value) => emit('update:modelValue', value),
  equals: (a, b) => Math.abs(a - b) <= props.tolerance,
  timeoutMs: () => props.syncTimeout,
})

// Thumb position while dragging. Nothing is sent until the operator
// releases (``change``), so a drag is one backend request, not fifty.
const dragValue = ref<number | null>(null)
const shownValue = computed(() => dragValue.value ?? displayValue.value)

const readValue = (event: Event) => parseFloat((event.target as HTMLInputElement).value)

const onInput = (event: Event) => {
  const val = readValue(event)
  if (Number.isFinite(val)) dragValue.value = val
}

const onChange = (event: Event) => {
  const val = readValue(event)
  dragValue.value = null
  if (Number.isFinite(val)) commit(val)
}
</script>

<template>
  <div class="m-2">
    <!-- Live readout row: receives the dragged / optimistic / backend value. -->
    <slot name="header" :value="shownValue" :is-synced="isSynced" :is-pending="isPending" />
    <!-- v-bind="$attrs" forces min, max, step to reach the input -->
    <input
        type="range"
        :value="shownValue ?? ''"
        :title="isSynced ? undefined : `${label}: waiting for backend value`"
        v-bind="$attrs"
        :disabled="disabled || isPending"
        :aria-busy="isPending"
        @input="onInput"
        @change="onChange"
        class="w-full h-2 bg-gray-900 rounded-lg appearance-none cursor-pointer accent-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-800 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
        :class="{
          'animate-pulse cursor-wait': isPending,
          'opacity-30': shownValue === null
        }"
    />
  </div>
</template>
