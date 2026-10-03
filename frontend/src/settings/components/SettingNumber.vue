<script setup lang="ts">
import SettingInput from "./SettingInput.vue";
import type { NumberSetting } from "../types/NumberSetting";

defineProps<{ setting: NumberSetting }>();

const parseNumber = (raw: string) => (raw.trim() === "" ? undefined : Number(raw));
</script>

<template>
  <SettingInput
      :setting="setting"
      input-type="number"
      :parse="parseNumber"
      :min="setting.bounds.min"
      :max="setting.bounds.max"
      :step="setting.bounds.step"
      :unit="setting.bounds.unit"
  />
</template>
