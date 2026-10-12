<script setup lang="ts">
import { onMounted, useAttrs, useTemplateRef } from 'vue'

// defineModel automatically handles the v-model binding from the parent
const model = defineModel<string | number>()

// Native ``autofocus`` only fires on page load, not for an input that
// appears later (a dialog) — focus it on mount instead.
const attrs = useAttrs()
const input = useTemplateRef<HTMLInputElement>('input')
onMounted(() => {
  if (attrs.autofocus !== undefined && attrs.autofocus !== false) input.value?.focus()
})

defineProps({
  // Allow passing a custom type (text, number, password, etc.), defaults to text
  type: {
    type: String,
    default: 'text'
  }
})
</script>

<template>
  <input
      ref="input"
      :type="type"
      v-model="model"
      class="bg-gray-900 border border-gray-600 rounded px-3 py-2 text-gray-100 placeholder-gray-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
  />
</template>