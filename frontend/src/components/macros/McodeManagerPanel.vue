<script setup lang="ts">
// Machine Config → M-codes sub-panel. Mirror of ``MacroManagerPanel``
// for the ``machine_config/m_codes/`` root. The names follow the
// strict LinuxCNC range ``M100..M199`` (regex ``^M1\d{2}$``) so the
// create-dialog form is a single name field with no kind picker —
// there is only one kind.
//
// Editing deep-links into the universal editor with the bare
// ``M<num>`` name (``/editor?source=m_codes&name=M101``). The
// universal editor's source-driven dispatch routes reads / writes
// through the machineconfig router's ``/m-codes/...`` endpoints,
// so the same CodeMirror surface that edits profiles and
// ``.macro`` files also edits M-codes — operators get one
// consistent editor experience across every kind.

import { computed, onMounted, ref, watch } from "vue";
import type { Ref } from "vue";
import { storeToRefs } from "pinia";

import { useMacrosStore, MACRO_KIND } from "../../stores/macrosStore";
import { ModalButtonStyle, useConfirm } from "../../core/confirm";
import { validateMacroKindName, MCODE_NAME_REGEX } from "../../parsers/macrosParser";
import { openInEditor } from "../../helpers/openInEditor";
import type { MacroEntry } from "../../stores/macrosTypes";
import {BaseButton, Icon} from "../../ui/index.ts";
import BaseCard from "../../ui/BaseCard.vue";
import BaseInput from "../../ui/BaseInput.vue";

const store = useMacrosStore();
const { mcodeFiles, isBusy } = storeToRefs(store);

const createOpen: Ref<boolean> = ref(false);
const createName: Ref<string> = ref("");
const createError: Ref<string> = ref("");

onMounted(async () => {
  await store.loadList(MACRO_KIND.MCODE);
});

const sorted = computed<MacroEntry[]>(() =>
  [...mcodeFiles.value].sort((a, b) => a.name.localeCompare(b.name)),
);

function formatSize(bytes: number): string {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  return (bytes / 1024).toFixed(1) + " KB";
}

function openEditor(name: string): void {
  // The universal editor handles the M-code body via
  // ``source='m_codes'`` — the store dispatches to
  // ``ModulesMachineconfigService.readMCode`` / ``writeMCode``.
  openInEditor({ source: "m_codes", name });
}

async function deleteMacro(name: string): Promise<void> {
  const shouldDelete = await useConfirm({
    title: `Delete ${name}`,
    question: `Delete "${name}"? This cannot be undone.`,
    confirmButtonText: "Delete",
    confirmButtonStyle: ModalButtonStyle.DANGER,
    rejectButtonText: "Cancel",
  });
  if (shouldDelete) {
    const result = await store.deleteMacro(MACRO_KIND.MCODE, name);
    if (result.ok) await store.loadList(MACRO_KIND.MCODE);
  }
}

function startCreate(): void {
  createName.value = "";
  createError.value = "";
  createOpen.value = true;
}

async function commitCreate(): Promise<void> {
  createError.value = "";
  const name = createName.value.trim();
  try {
    validateMacroKindName(MACRO_KIND.MCODE, name);
  } catch (error: unknown) {
    createError.value = error instanceof Error ? error.message : String(error);
    return;
  }
  if (mcodeFiles.value.some((row) => row.name === name)) {
    createError.value = `M-code "${name}" already exists.`;
    return;
  }
  // Seed with a newline so the initial PUT succeeds. The dialog
  // closes; the operator then clicks Edit (or opens the URL
  // ``/config/<name>`` directly) to reach the universal editor.
  const result = await store.saveMacro(MACRO_KIND.MCODE, name, "\n");
  if (result.ok) {
    createOpen.value = false;
    await store.loadList(MACRO_KIND.MCODE);
  } else if (store.lastError) {
    createError.value = store.lastError;
  }
}

watch(() => store.lastError, (value) => {
  if (value && createOpen.value) createError.value = value;
});
</script>

<template>
  <BaseCard title="⚙️ M-Codes">
    <template #header-actions>
      <span class="text-xs text-gray-400 font-mono">
        {{ sorted.length }} M-code{{ sorted.length === 1 ? '' : 's' }}
      </span>
      <BaseButton
        variant="primary"
        size="sm"
        :disabled="isBusy"
        @click="startCreate"
        data-test="mcodes-create"
      >
        + New M-code
      </BaseButton>
    </template>

    <div v-if="sorted.length === 0" class="text-center text-gray-500 text-sm">
      No M-codes yet. Use <span class="font-mono">+ New M-code</span>
      to create one (M100..M199).
    </div>

    <ul v-else class="space-y-2">
      <li
        v-for="row in sorted"
        :key="row.name"
        class="flex items-center justify-between gap-4 rounded-lg border border-gray-700 bg-gray-900/60 p-3"
      >
        <div class="min-w-0">
          <div class="font-mono text-sm font-semibold text-gray-100 truncate flex items-center gap-2">
            <span class="text-yellow-300">M</span>{{ row.name.slice(1) }}
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-yellow-700/40 text-yellow-200 uppercase tracking-wider">
              M-code
            </span>
          </div>
          <div class="text-xs text-gray-400">
            {{ formatSize(row.size_bytes) }}
          </div>
        </div>
        <div class="flex items-center gap-3 shrink-0">
          <BaseButton
            variant="primary"
            size="sm"
            :disabled="isBusy"
            @click="openEditor(row.name)"
            :data-test="`mcodes-edit-${row.name}`"
          >
            <Icon name="edit"  />
          </BaseButton>
          <BaseButton
            variant="secondary"
            size="sm"
            :disabled="isBusy"
            @click="deleteMacro(row.name)"
            :data-test="`mcodes-delete-${row.name}`"
          >
            <Icon name="trash"  />
          </BaseButton>
        </div>
      </li>
    </ul>

    <!-- Create modal: a single name field. The regex is shown next
         to the input so an operator sees the constraint without
         having to read the source. -->
    <div
      v-if="createOpen"
      class="fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-4"
      @click.self="createOpen = false"
    >
      <form
        class="w-full max-w-md space-y-4 rounded-lg border border-gray-600 bg-gray-800 p-5"
        @submit.prevent="commitCreate"
      >
        <h3 class="text-lg font-semibold text-gray-100">New M-code</h3>
        <div>
          <label class="block text-xs uppercase tracking-wider text-gray-400 mb-1">
            Name
          </label>
          <BaseInput
            v-model="createName"
            type="text"
            autofocus
            placeholder="e.g. M101"
            class="w-full font-mono"
            data-test="mcodes-create-name"
          />
          <p class="mt-1 text-[11px] text-gray-500">
            <code v-if="MCODE_NAME_REGEX">{{ MCODE_NAME_REGEX }}</code>
            — M100..M199.
          </p>
        </div>
        <p
          v-if="createError"
          class="text-xs text-red-400 font-mono"
          data-test="mcodes-create-error"
        >
          {{ createError }}
        </p>
        <div class="flex justify-end gap-2">
          <BaseButton variant="secondary" @click="createOpen = false">
            Cancel
          </BaseButton>
          <BaseButton
            variant="primary"
            type="submit"
            :disabled="isBusy || !createName.trim()"
            data-test="mcodes-create-submit"
          >
            Create
          </BaseButton>
        </div>
      </form>
    </div>
  </BaseCard>
</template>