<script setup lang="ts">
// The exclude-objects sub-menu's list (opened by PrintObjects).
import { BaseButton } from "../../ui/index.ts";
import { usePrintTuning } from "../../composables/usePrintTuning";

const { state, busy, exclude } = usePrintTuning();
</script>

<template>
  <div v-if="state?.objects?.length" class="space-y-1 rounded border border-gray-700 p-2" data-testid="print-tuning-objects">
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
</template>
