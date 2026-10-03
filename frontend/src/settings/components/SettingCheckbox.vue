<script setup lang="ts">
// Editor for a CheckboxSetting. BaseCheckbox's sync contract keeps the
// requested value on screen until ``save`` adopts the backend echo.
import BaseCheckbox from "../../ui/BaseCheckbox.vue";
import type { CheckboxSetting } from "../types/CheckboxSetting";

defineProps<{ setting: CheckboxSetting }>();
</script>

<template>
  <BaseCheckbox
      :model-value="setting.value"
      :label="setting.label"
      :data-testid="`setting-${setting.key}`"
      @update:model-value="(v: boolean) => setting.save(v)"
  />
</template>
