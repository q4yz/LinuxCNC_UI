<script setup lang="ts" generic="V extends string | number">
// Editor for a SelectSetting (BaseSelect keeps the requested option on
// screen until the backend echo confirms it). Generic so a narrowed
// setting (e.g. ``SelectSetting<TemperatureUnit>``) type-checks.
import BaseSelect from "../../ui/BaseSelect.vue";
import type { SelectSetting } from "../types/SelectSetting";

const props = defineProps<{ setting: SelectSetting<V> }>();

// BaseSelect emits ``string | number``; only the setting's own choices
// can be selected, and ``save`` validates against them anyway.
const onUpdate = (value: string | number) => void props.setting.save(value as V);
</script>

<template>
  <BaseSelect
      :model-value="setting.value"
      :label="setting.label"
      :data-testid="`setting-${setting.key}`"
      @update:model-value="onUpdate"
  >
    <option v-for="choice in setting.choices" :key="String(choice.value)" :value="choice.value">
      {{ choice.label }}
    </option>
  </BaseSelect>
</template>
