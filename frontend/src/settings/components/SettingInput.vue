<script setup lang="ts" generic="T extends string | number">
// Text/number editor on the same sync contract as BaseCheckbox/Range/
// Select (``useBackendSync``): typing edits a local draft, ``change``
// (Enter / blur) requests the value, the backend echo confirms it, a
// failed save reverts after the sync timeout. ``BaseInput`` is left
// alone — it is a plain local ``v-model`` input across the app.
import { computed, ref } from "vue";
import { useBackendSync } from "../../ui/useBackendSync";
import type { BaseSetting } from "../core/BaseSetting";
import { settingsLog } from "../core/settingsLog";

const props = defineProps<{
  setting: BaseSetting<T>;
  inputType: "text" | "number";
  /** Turns the raw input string into a candidate value (validated by the setting). */
  parse: (raw: string) => unknown;
  min?: number;
  max?: number;
  step?: number;
  placeholder?: string;
  unit?: string;
}>();

const { displayValue, isPending, isSynced, commit } = useBackendSync<T>({
  label: () => props.setting.label,
  source: () => props.setting.value,
  hasListener: () => true,
  emit: (value) => void props.setting.save(value),
});

// What the operator is typing; ``null`` = show the synced/requested value.
const draft = ref<string | null>(null);
const shown = computed(() => draft.value ?? (displayValue.value === null ? "" : String(displayValue.value)));

function onChange(event: Event) {
  const raw = (event.target as HTMLInputElement).value;
  draft.value = null;
  const candidate = props.setting.validate(props.parse(raw));
  if (candidate === undefined) {
    settingsLog("warning", `${props.setting.label}: "${raw}" is not a valid value — not saved`);
    return;
  }
  commit(candidate);
}
</script>

<template>
  <div class="flex items-center gap-2">
    <input
        :type="inputType"
        :value="shown"
        :min="min"
        :max="max"
        :step="step"
        :placeholder="placeholder"
        :disabled="isPending || !isSynced"
        :aria-busy="isPending"
        :title="isSynced ? undefined : `${setting.label}: waiting for backend value`"
        :data-testid="`setting-${setting.key}`"
        class="bg-gray-900 border border-gray-600 rounded px-3 py-2 text-gray-100 placeholder-gray-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        :class="{ 'animate-pulse cursor-wait': isPending, 'border-dashed': !isSynced }"
        @input="draft = ($event.target as HTMLInputElement).value"
        @change="onChange"
    />
    <span v-if="unit" class="text-xs text-gray-400">{{ unit }}</span>
  </div>
</template>
