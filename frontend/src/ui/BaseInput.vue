<script setup lang="ts">
// defineModel automatically handles the v-model binding from the parent
const model = defineModel<string | number>()

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
      :type="type"
      v-model="model"
      class="bg-gray-900 border border-gray-600 rounded px-3 py-2 text-gray-100 placeholder-gray-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
  />
</template>