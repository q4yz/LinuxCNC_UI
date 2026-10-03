<script setup lang="ts">
// One row of the generated Settings view: label, help text, the
// setting's own editor (``setting.component``) and a reset-to-default
// button. Critical settings are read fresh every time the row mounts —
// they are never trusted from the session cache.
import { onMounted } from "vue";
import type { BaseSetting } from "../core/BaseSetting";

const props = defineProps<{ setting: BaseSetting<unknown> }>();

onMounted(() => {
  if (props.setting.critical) void props.setting.load();
});
</script>

<template>
  <div class="flex flex-wrap items-center justify-between gap-4 rounded bg-gray-900/60 border border-gray-700 px-4 py-3">
    <div class="min-w-0 flex-1">
      <div class="text-sm font-medium text-gray-200">
        {{ setting.label }}
        <span
            v-if="setting.critical"
            class="ml-2 rounded border border-amber-700 px-1 text-[10px] uppercase tracking-wider text-amber-300"
            title="Read fresh from the backend every time — other parts of the system depend on it"
        >live</span>
      </div>
      <p v-if="setting.description" class="mt-0.5 text-xs text-gray-400">{{ setting.description }}</p>
      <p class="mt-0.5 font-mono text-[10px] text-gray-500">{{ setting.key }}</p>
    </div>
    <div class="flex items-center gap-2">
      <component :is="setting.component" :setting="setting" />
      <button
          v-if="setting.isStored"
          type="button"
          class="text-xs text-gray-400 hover:text-gray-200 underline"
          :title="`Reset to default (${JSON.stringify(setting.defaultValue)})`"
          :data-testid="`setting-reset-${setting.key}`"
          @click="setting.reset()"
      >
        reset
      </button>
    </div>
  </div>
</template>
