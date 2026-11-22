<script setup lang="ts">
// The × of a floating window, in the header that holds its windowChrome.
import Icon from "./Icon.vue";
import type { WindowChrome } from "../composables/windowChrome";

defineProps<{ chrome: WindowChrome }>();
</script>

<template>
  <button
      type="button"
      class="-my-1 -mr-2 flex h-7 w-7 items-center justify-center rounded text-gray-400 hover:bg-gray-600 hover:text-white"
      :aria-label="`Close ${chrome.title}`"
      data-testid="window-close"
      @click="chrome.close()"
  ><Icon name="close" class="h-4 w-4" /></button>
</template>
