<script setup lang="ts">
// The exclude-objects sub-menu's toggle (EXCLUDE_OBJECT) on the Programs
// card: "Objects (n)", the excluded count, opens PrintObjectList.
import { computed } from "vue";
import { Icon } from "../../ui/index.ts";
import { usePrintTuning } from "../../composables/usePrintTuning";

const open = defineModel<boolean>("open", { default: false });
const { state } = usePrintTuning();
const excludedCount = computed(() => state.value?.objects?.filter((o) => o.excluded).length ?? 0);
</script>

<template>
  <button
      v-if="state?.objects?.length"
      type="button"
      class="flex shrink-0 items-center gap-1 rounded border border-gray-600 px-2 py-1 text-xs text-gray-300 hover:border-gray-500 hover:text-white"
      :class="open ? 'border-blue-500 text-white' : ''"
      :aria-expanded="open"
      data-testid="print-tuning-objects-toggle"
      @click="open = !open"
  >
    Objects ({{ state.objects.length }})
    <span v-if="excludedCount" class="text-red-300">· {{ excludedCount }} excluded</span>
    <Icon name="chevronDown" class="h-3.5 w-3.5 transition-transform" :class="open ? 'rotate-180' : ''" />
  </button>
</template>
