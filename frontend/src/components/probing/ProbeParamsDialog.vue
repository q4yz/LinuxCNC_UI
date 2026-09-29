<script setup lang="ts">
// Asks for the cycle-specific values a probing macro needs (search
// distance, boss diameter, ...) before it runs. Same visual language
// as ``ui/Confirm.vue`` — gray-900 panel on a black/70 backdrop.
//
// The field list comes from ``config/probing.ts``; the host passes the
// last-used values in ``values`` so a repeated cycle is one click.
// ``run`` fires only with every field a finite number at or above its
// ``min`` — the Run button stays disabled otherwise.

import {computed, reactive, watch} from "vue";

import BaseButton from "../../ui/BaseButton.vue";
import BaseInput from "../../ui/BaseInput.vue";
import Icon from "../../ui/Icon.vue";
import type {ProbeField} from "../../config/probing";

const props = defineProps<{
  open: boolean;
  title: string;
  fields: ProbeField[];
  values: Record<string, number>;
}>();

const emit = defineEmits<{
  (e: "update:open", open: boolean): void;
  (e: "run", values: Record<string, number>): void;
}>();

const draft = reactive<Record<string, number | string>>({});

// Re-seed the draft every time the dialog opens, so a cancelled edit
// never leaks into the next cycle.
watch(
    () => props.open,
    (open) => {
      if (!open) return;
      for (const key of Object.keys(draft)) delete draft[key];
      for (const field of props.fields) {
        draft[field.key] = props.values[field.key] ?? field.default;
      }
    },
    {immediate: true},
);

function parsed(field: ProbeField): number | null {
  const raw = draft[field.key];
  const value = typeof raw === "number" ? raw : Number.parseFloat(String(raw));
  if (!Number.isFinite(value)) return null;
  if (field.min !== undefined && value < field.min) return null;
  return value;
}

const isValid = computed(() => props.fields.every((f) => parsed(f) !== null));

function close() {
  emit("update:open", false);
}

function run() {
  if (!isValid.value) return;
  const values: Record<string, number> = {};
  for (const field of props.fields) values[field.key] = parsed(field) as number;
  emit("update:open", false);
  emit("run", values);
}
</script>

<template>
  <Teleport to="body">
    <div
        v-if="open"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
        data-testid="probe-dialog-backdrop"
        @click="close"
        @keydown.esc="close"
    >
      <form
          class="w-full max-w-sm rounded-lg border border-gray-700 bg-gray-900 p-6 text-white"
          role="dialog"
          aria-modal="true"
          aria-labelledby="probe-dialog-title"
          data-testid="probe-dialog"
          @click.stop
          @submit.prevent="run"
      >
        <header class="flex items-start justify-between gap-4">
          <h2 id="probe-dialog-title" class="text-lg font-semibold text-gray-100">{{ title }}</h2>
          <BaseButton
              type="button"
              class="text-xl leading-none text-gray-400 hover:text-white"
              aria-label="Close"
              @click="close"
          >
            <Icon name="close" size="h-4 w-4"/>
          </BaseButton>
        </header>

        <div class="mt-4 space-y-3">
          <label v-for="field in fields" :key="field.key" class="block text-sm text-gray-200">
            <span class="mb-1 block text-xs font-medium text-gray-400">{{ field.label }} (mm)</span>
            <BaseInput
                v-model="draft[field.key]"
                type="number"
                step="0.01"
                :min="field.min"
                class="w-full"
                :data-testid="`probe-field-${field.key}`"
            />
          </label>
        </div>

        <footer class="mt-6 flex justify-end gap-3">
          <BaseButton type="button" variant="secondary" data-testid="probe-dialog-cancel" @click="close">
            Cancel
          </BaseButton>
          <BaseButton type="submit" variant="primary" :disabled="!isValid" data-testid="probe-dialog-run">
            Run Probe
          </BaseButton>
        </footer>
      </form>
    </div>
  </Teleport>
</template>
