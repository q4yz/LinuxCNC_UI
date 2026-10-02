<script setup lang="ts">
import { computed } from 'vue'
import { useBackendSync, DEFAULT_SYNC_TIMEOUT_MS } from './useBackendSync'

type OptionValue = string | number

const props = withDefaults(defineProps<{
  // Backend value. ``null`` = not received yet; never defaulted.
  modelValue: OptionValue | null
  // Operator-facing name, used in every sync log line.
  label: string
  disabled?: boolean
  syncTimeout?: number
  // Declared as a prop so we can detect whether the parent is listening.
  'onUpdate:modelValue'?: (newValue: OptionValue) => void
}>(), {
  disabled: false,
  syncTimeout: DEFAULT_SYNC_TIMEOUT_MS,
})

const emit = defineEmits<{
  (e: 'update:modelValue', newValue: OptionValue): void
}>()

const { displayValue, isPending, isSynced, commit } = useBackendSync<OptionValue>({
  label: () => props.label,
  source: () => props.modelValue,
  hasListener: () => !!props['onUpdate:modelValue'],
  emit: (value) => emit('update:modelValue', value),
  timeoutMs: () => props.syncTimeout,
})

// Routed through ``v-model`` so Vue keeps the <option :value> types
// (numbers stay numbers) instead of us parsing ``event.target.value``.
const selected = computed<OptionValue | null>({
  get: () => displayValue.value,
  set: (value) => {
    if (value != null) commit(value)
  },
})
</script>

<template>
  <select
      v-model="selected"
      :title="isSynced ? undefined : `${label}: waiting for backend value`"
      :disabled="disabled || isPending"
      :aria-busy="isPending"
      class="bg-gray-900 border border-gray-600 text-gray-200 rounded px-2 py-1 outline-none font-bold focus:border-blue-500 focus:ring-1 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
      :class="{
        'animate-pulse cursor-wait': isPending,
        'border-dashed text-gray-500': selected === null
      }"
  >
    <!-- Unsynced placeholder: shown instead of guessing the first option. -->
    <option v-if="selected === null" :value="null" disabled>—</option>
    <!-- The <option> tags will be injected here -->
    <slot />
  </select>
</template>
