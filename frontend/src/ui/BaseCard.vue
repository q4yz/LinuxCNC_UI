<template>

  <div class="rounded-lg bg-gray-800 border border-gray-700 shadow-md ">



    <div v-if="title" class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex items-center justify-between">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">
        {{ title }}
      </h2>


      <div class="flex items-center space-x-2">
        <slot name="header-actions" />
      </div>
    </div>
    <div>
      <slot />
    </div>


    <div v-if="footer" class="bg-gray-700/30 px-4 py-3 flex justify-between text-sm text-gray-400">
      <span> {{ footer }}</span>
      <div class="flex items-center space-x-2">
        <slot name="footer-actions" />
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
withDefaults(
  defineProps<{
    title?: string;
    footer?: string;
  }>(),
  {
    title: '',
    footer: '',
  },
);
</script>
