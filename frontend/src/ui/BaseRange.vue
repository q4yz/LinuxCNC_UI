<script setup lang="ts">
// Disable automatic attribute fallthrough so we can target the input directly
defineOptions({
  inheritAttrs: false
})

const model = defineModel<number>({ default: 0 })
const emit = defineEmits(['touched'])

const onInput = (event: Event) => {
  const target = event.target as HTMLInputElement
  const val = parseFloat(target.value)
  if (Number.isFinite(val)) {
    model.value = val
    emit('touched')
  }
}
</script>

<template>
  <div class="m-2">
    <!-- v-bind="$attrs" forces min, max, step, and disabled to reach the input -->
    <input
        type="range"
        :value="model"
        @input="onInput"
        v-bind="$attrs"
        class="w-full h-2 bg-gray-900 rounded-lg appearance-none cursor-pointer accent-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-800 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
    />
  </div>
</template>