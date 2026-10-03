<script setup lang="ts">
// Editor for a RangeSetting (BaseRange: one save per release, not per drag step).
import BaseRange from "../../ui/BaseRange.vue";
import type { RangeSetting } from "../types/RangeSetting";

defineProps<{ setting: RangeSetting }>();
</script>

<template>
  <BaseRange
      :model-value="setting.value"
      :label="setting.label"
      :min="setting.bounds.min"
      :max="setting.bounds.max"
      :step="setting.bounds.step ?? 1"
      :data-testid="`setting-${setting.key}`"
      @update:model-value="(v: number) => setting.save(v)"
  >
    <template #header="{ value }">
      <div class="text-right font-mono text-sm text-blue-300">
        {{ value ?? '—' }} {{ setting.bounds.unit ?? '' }}
      </div>
    </template>
  </BaseRange>
</template>
