<script setup lang="ts">
// Excluding objects of the running print (EXCLUDE_OBJECT) — a collapsed
// sub-menu on the Programs card while a print runs or is paused.
import { computed, ref } from "vue";
import { BaseButton, Icon } from "../../ui/index.ts";
import { usePrintTuning } from "../../composables/usePrintTuning";

const { state, busy, exclude } = usePrintTuning();
const open = ref(false);
const excludedCount = computed(() => state.value?.objects?.filter((o) => o.excluded).length ?? 0);
</script>

<template>
  <div v-if="state?.objects?.length" class="rounded border border-gray-700" data-testid="print-tuning-objects">
    <button
        type="button"
        class="flex w-full items-center justify-between px-2 py-1.5 text-xs uppercase tracking-wider text-gray-400 hover:text-gray-200"
        :aria-expanded="open"
        data-testid="print-tuning-objects-toggle"
        @click="open = !open"
    >
      <span>
        Objects ({{ state.objects.length }})
        <span v-if="excludedCount" class="normal-case tracking-normal text-red-300"> · {{ excludedCount }} excluded</span>
      </span>
      <Icon name="chevronDown" class="h-4 w-4 transition-transform" :class="open ? 'rotate-180' : ''" />
    </button>
    <div v-if="open" class="space-y-1 border-t border-gray-700 p-2">
      <div
          v-for="object in state.objects"
          :key="object.index"
          class="flex items-center justify-between rounded border border-gray-700 px-2 py-1"
          :class="object.excluded ? 'opacity-60' : ''"
      >
        <span class="truncate font-mono text-xs" :class="object.excluded ? 'line-through text-gray-500' : 'text-gray-200'">
          {{ object.name }}
        </span>
        <BaseButton
            size="sm"
            :variant="object.excluded ? 'secondary' : 'danger'"
            :disabled="busy"
            @click="exclude(object.index, !object.excluded)"
        >{{ object.excluded ? "Include" : "Exclude" }}</BaseButton>
      </div>
      <p class="text-[10px] text-gray-500">
        Takes effect for the parts LinuxCNC has not read ahead yet (a few seconds).
      </p>
    </div>
  </div>
</template>
