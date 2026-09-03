<script setup lang="ts">
// Machine Config → Macros management panel. Lives inside
// ``EditorView`` next to ``ProfilesExplorer`` / ``CompilerPanel``.
//
// Surface:
//   * List of ``macro`` + ``ngc`` files (kind-tagged) with body
//     size + per-row "Edit" / "Delete" actions. "Delete" uses
//     ``useConfirm({ ModalButtonStyle.DANGER })`` from
//     ``core/confirm.js`` (same pattern as ``ProfilesExplorer.vue``).
//   * "+ New macro" button opens an inline form: name input +
//     kind picker (Macro / NGC subroutine) + Save / Cancel.
//     Validation runs through ``validateMacroKindName(kind, name)``
//     so a typo surfaces before the round-trip.
//
// M-codes have their own ``McodeManagerPanel`` because they live
// in a different on-disk root (``machine_config/m_codes/``) and
// follow a stricter name regex (``^M1\d{2}$``).
//
// The text editor itself lives in ``EditorView`` — this panel
// never embeds ``Editor.vue``. The "+ New macro" flow creates the
// file via the store (so collisions are caught up-front) then
// pushes ``/editor?source=macros&name=<filename>`` so the operator
// lands in the universal editor. The unsaved-changes guard lives
// in ``EditorView`` itself (see ``router/guards/unsavedChangesGuard.js``).

import { computed, onMounted, ref, watch } from "vue";
import type { Ref } from "vue";
import { storeToRefs } from "pinia";

import { useMacrosStore, MACRO_KIND } from "../../stores/macrosStore";
import { ModalButtonStyle, useConfirm } from "../../core/confirm";
import { validateMacroKindName } from "../../parsers/macrosParser";
import { openInEditor } from "../../helpers/openInEditor";
import type { MacroKind } from "../../stores/macrosTypes";
import { BaseButton } from "../../ui/index.ts";
import BaseCard from "../../ui/BaseCard.vue";
import BaseInput from "../../ui/BaseInput.vue";
import {Icon} from "../../ui";

const store = useMacrosStore();
const { macroFiles, ngcFiles, contents, isBusy } = storeToRefs(store);

const createOpen: Ref<boolean> = ref(false);
const createKind: Ref<MacroKind> = ref(MACRO_KIND.MACRO);
const createName: Ref<string> = ref("");
const createError: Ref<string> = ref("");

onMounted(async () => {
  // Lazy load both halves of ``<repo>/macros/`` so the panel
  // mounts with content already populated.
  await Promise.all([
    store.loadList(MACRO_KIND.MACRO),
    store.loadList(MACRO_KIND.NGC),
  ]);
});

interface MacroCard {
  kind: MacroKind;
  name: string;
  displayName: string;
  size: number;
}

const macroCards = computed<MacroCard[]>(() =>
  [...macroFiles.value, ...ngcFiles.value]
    .map((row): MacroCard => {
      const cached = contents.value[`${row.kind}:${row.name}`];
      const size = typeof cached === "string" ? new Blob([cached]).size : 0;
      return {
        kind: row.kind,
        name: row.name,
        displayName:
          row.kind === MACRO_KIND.NGC
            ? `${row.name}.ngc`
            : `${row.name}.macro`,
        size,
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name)),
);

function formatSize(bytes: number): string {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

// "Edit" used to mount ``Editor`` inline inside a full-height
// modal. Issue #132 moves the editor to ``EditorView`` only; we
// push ``/editor?source=macros&name=<displayedFilename>`` here and
// let the universal editor handle the read/write surface.
function openInEditorView(kind: MacroKind, name: string): void {
  const displayedName = kind === MACRO_KIND.NGC ? `${name}.ngc` : `${name}.macro`;
  openInEditor({
    source: 'macros',
    name: displayedName,
    readOnly: false,
  });
}

async function deleteMacro(kind: MacroKind, name: string): Promise<void> {
  const display =
    kind === MACRO_KIND.NGC ? `${name}.ngc` : `${name}.macro`;
  const shouldDelete = await useConfirm({
    title: `Delete ${display}`,
    question: `Delete "${display}"? This cannot be undone.`,
    confirmButtonText: "Delete",
    confirmButtonStyle: ModalButtonStyle.DANGER,
    rejectButtonText: "Cancel",
  });
  if (shouldDelete) {
    const result = await store.deleteMacro(kind, name);
    if (result.ok) {
      await store.loadList(kind);
    }
  }
}

function startCreate(): void {
  createName.value = "";
  createKind.value = MACRO_KIND.MACRO;
  createError.value = "";
  createOpen.value = true;
}

async function commitCreate(): Promise<void> {
  createError.value = "";
  const name = createName.value.trim();
  try {
    validateMacroKindName(createKind.value, name);
  } catch (error: unknown) {
    createError.value = error instanceof Error ? error.message : String(error);
    return;
  }
  // Cross-kind collision: ``home_all`` (macro) and ``home_all`` (ngc)
  // can both exist in ``<repo>/macros/`` because they differ only
  // by extension. Reject same-name + same-kind pairs at the form.
  const sameKindContainer =
    createKind.value === MACRO_KIND.MACRO ? macroFiles : ngcFiles;
  if (sameKindContainer.value.some((row) => row.name === name)) {
    createError.value = `${name} already exists as a ${createKind.value}.`;
    return;
  }
  // FastAPI rejects zero-byte text/plain bodies with 422. Seed
  // with a newline so the initial PUT succeeds and the editor
  // opens on an effectively blank file.
  const result = await store.saveMacro(createKind.value, name, "\n");
  if (result.ok) {
    createOpen.value = false;
    await openInEditorView(createKind.value, name);
  } else if (store.lastError) {
    createError.value = store.lastError;
  }
}

watch(() => store.lastError, (value) => {
  if (value && createOpen.value) createError.value = value;
});
</script>

<template>
  <BaseCard title="🧩 Macros &amp; NGC" >
    <template #header-actions>
      <span class="text-xs text-gray-400 font-mono">
        {{ macroCards.length }} file{{ macroCards.length === 1 ? '' : 's' }}
      </span>
      <BaseButton
        variant="primary"
        size="sm"
        :disabled="isBusy"
        @click="startCreate"
        data-test="macros-create"
      >
        + New macro
      </BaseButton>
    </template>

    <div v-if="macroCards.length === 0" class="text-center text-gray-500 text-sm">
      No macros yet. Use <span class="font-mono">+ New macro</span> to create one.
    </div>

    <ul v-else class="space-y-2">
      <li
        v-for="card in macroCards"
        :key="`${card.kind}:${card.name}`"
        class="flex items-center justify-between gap-4 rounded-lg border border-gray-700 bg-gray-900/60 p-3"
      >
        <div class="min-w-0">
          <div class="font-mono text-sm font-semibold text-gray-100 truncate flex items-center gap-2">
            🧩 {{ card.displayName }}
            <span
              class="text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wider"
              :class="
                card.kind === 'macro'
                  ? 'bg-blue-700/40 text-blue-200'
                  : 'bg-purple-700/40 text-purple-200'
              "
            >
              {{ card.kind }}
            </span>
          </div>
          <div class="text-xs text-gray-400">
            {{ formatSize(card.size) }}
          </div>
        </div>
        <div class="flex items-center gap-3 shrink-0">
          <BaseButton
            variant="primary"
            size="sm"
            :disabled="isBusy"
            @click="openInEditorView(card.kind, card.name)"
            :data-test="`macros-edit-${card.kind}-${card.name}`"
          >
            <Icon name="edit"  />
          </BaseButton>
          <BaseButton
            variant="secondary"
            size="sm"
            :disabled="isBusy"
            @click="deleteMacro(card.kind, card.name)"
            :data-test="`macros-delete-${card.kind}-${card.name}`"
          >
            <Icon name="trash" />
          </BaseButton>
        </div>
      </li>
    </ul>

    <!-- Create modal -->
    <div
      v-if="createOpen"
      class="fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-4"
      @click.self="createOpen = false"
    >
      <form
        class="w-full max-w-md space-y-4 rounded-lg border border-gray-600 bg-gray-800 p-5 shadow-2xl"
        @submit.prevent="commitCreate"
      >
        <h3 class="text-lg font-semibold text-gray-100">New macro</h3>
        <div>
          <label class="block text-xs uppercase tracking-wider text-gray-400 mb-1">
            Kind
          </label>
          <div class="flex gap-3 text-sm">
            <label class="flex items-center gap-2 cursor-pointer">
              <input
                v-model="createKind"
                type="radio"
                value="macro"
                data-test="macros-create-kind-macro"
              />
              <span>Macro (<code>.macro</code>)</span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer">
              <input
                v-model="createKind"
                type="radio"
                value="ngc"
                data-test="macros-create-kind-ngc"
              />
              <span>LinuxCNC NGC (<code>.ngc</code>)</span>
            </label>
          </div>
        </div>
        <div>
          <label class="block text-xs uppercase tracking-wider text-gray-400 mb-1">
            Name
          </label>
          <BaseInput
            v-model="createName"
            type="text"
            autofocus
            placeholder="e.g. home_all"
            class="w-full font-mono"
            data-test="macros-create-name"
          />
          <p class="mt-1 text-[11px] text-gray-500">
            Letters, digits, <code>_ - .</code>; 1–64 characters.
          </p>
        </div>
        <p
          v-if="createError"
          class="text-xs text-red-400 font-mono"
          data-test="macros-create-error"
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
            data-test="macros-create-submit"
          >
            Create
          </BaseButton>
        </div>
      </form>
    </div>

    <!-- Edit modal removed: the universal editor contract (issue
         #132) pushes the operator to ``/editor?source=macros&name=...``
         instead of mounting ``Editor`` inline. -->
  </BaseCard>
</template>