<script setup lang="ts">
import SettingInput from "./SettingInput.vue";
import type { TextSetting } from "../types/TextSetting";

defineProps<{ setting: TextSetting }>();

const parseText = (raw: string) => raw.trim();
</script>

<template>
  <SettingInput
      :setting="setting"
      input-type="text"
      :parse="parseText"
      :placeholder="setting.constraints.placeholder"
  />
</template>
