<script setup lang="ts">
const model = defineModel<string | number>()
</script>

<template>
  <select
      v-model="model"
      class="bg-gray-900 border border-gray-600 text-gray-200 rounded px-2 py-1 outline-none font-bold focus:border-blue-500 focus:ring-1 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
  >
    <!-- The <option> tags will be injected here -->
    <slot />
  </select>
</template>