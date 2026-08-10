<script setup>
// Machine Config → Macros management panel. Lives inside
// ``EditorView`` next to ``ProfilesExplorer`` / ``CompilerPanel``.
//
// Surface:
//   * List of macros with byte size + per-row "Edit" / "Delete"
//     actions.
//   * "+ New macro" button opens an inline form that pre-fills an
//     empty body and runs the name through ``validateMacroName`` so
//     a typo never reaches the backend.
//
// The text editor rides on the existing ``Editor.vue`` component
// inside a full-height modal — no new editor dependency. Save is
// debounced through a manual "pristineContent" mirror so the modal
// can prompt on Close when the body is dirty (mirrors the
// ``EditorView`` unsaved-changes guard, scoped to the macro modal).

import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";

import Editor from "../../../components/Editor.vue";
import { useMacrosStore } from "../store.js";
import { ModalButtonStyle, useConfirm } from "../../../core/confirm.js";
import { validateMacroName } from "../parser.js";

const store = useMacrosStore();
const { macros, contents, isBusy } = storeToRefs(store);

const editorOpen = ref(false);
const editorName = ref("");
const editorContent = ref("");
const editorPristine = ref("");
const editorSaving = ref(false);
const editorLoading = ref(false);

const createOpen = ref(false);
const createName = ref("");
const createError = ref("");

onMounted(async () => {
  if (macros.value.length === 0) await store.loadList();
});

const macroCards = computed(() =>
  macros.value.map((name) => {
    const cached = contents.value[name];
    const size = typeof cached === "string" ? new Blob([cached]).size : 0;
    return { name, size };
  }),
);

function formatSize(bytes) {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

async function openEditor(name) {
  editorName.value = name;
  editorSaving.value = false;
  editorLoading.value = true;
  editorContent.value = contents.value[name] ?? "";
  editorPristine.value = editorContent.value;
  editorOpen.value = true;
  try {
    const payload = await store.ensureMacroContent(name);
    if (payload != null) {
      editorContent.value = payload;
      editorPristine.value = payload;
    }
  } finally {
    editorLoading.value = false;
  }
}

const editorIsDirty = computed(
  () => editorContent.value !== editorPristine.value,
);

async function closeEditor(force = false) {
  if (!force && editorIsDirty.value) {
    const shouldClose = await useConfirm({
      title: "Unsaved changes",
      question: "Close the macro editor? Unsaved edits will be discarded.",
      confirmButtonText: "Discard",
      confirmButtonStyle: ModalButtonStyle.DANGER,
      rejectButtonText: "Keep editing",
    });
    if (!shouldClose) return;
  }
  editorOpen.value = false;
  editorName.value = "";
  editorContent.value = "";
  editorPristine.value = "";
}

async function saveEditor() {
  if (!editorName.value) return;
  editorSaving.value = true;
  try {
    // Same FastAPI 422 trap as ``commitCreate``: an empty body
    // never reaches the backend. Normalise ``""`` → ``"\n"`` so
    // a user who fully clears the editor can still save.
    const body = editorContent.value.length === 0 ? "\n" : editorContent.value;
    const ok = await store.saveMacro(editorName.value, body);
    if (ok) {
      editorPristine.value = body;
      editorContent.value = body;
    }
  } finally {
    editorSaving.value = false;
  }
}

async function saveAndCloseEditor() {
  await saveEditor();
  if (editorContent.value === editorPristine.value) {
    editorOpen.value = false;
  }
}

async function deleteMacro(name) {
  const shouldDelete = await useConfirm({
    title: "Delete macro",
    question: `Delete "${name}"? This cannot be undone.`,
    confirmButtonText: "Delete",
    confirmButtonStyle: ModalButtonStyle.DANGER,
    rejectButtonText: "Cancel",
  });
  if (shouldDelete) await store.deleteMacro(name);
}

function startCreate() {
  createName.value = "";
  createError.value = "";
  createOpen.value = true;
}

async function commitCreate() {
  createError.value = "";
  const name = createName.value.trim();
  try {
    validateMacroName(name);
  } catch (error) {
    createError.value = error instanceof Error ? error.message : String(error);
    return;
  }
  if (macros.value.includes(name)) {
    createError.value = `Macro "${name}" already exists.`;
    return;
  }
  // FastAPI rejects a zero-byte ``text/plain`` body with 422
  // (``loc:["body"], msg:"Field required"``). Seed with a
  // single newline so the initial PUT succeeds and the editor
  // opens on an effectively blank file. The user will type over
  // it on first edit.
  const ok = await store.saveMacro(name, "\n");
  if (ok) {
    createOpen.value = false;
    await openEditor(name);
  } else if (store.lastError) {
    createError.value = store.lastError;
  }
}

watch(() => store.lastError, (value) => {
  if (value && createOpen.value) createError.value = value;
});
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden">
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex justify-between items-center">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        <span class="mr-2">🧩</span> Macros
      </h2>
      <div class="flex items-center gap-3">
        <span class="text-xs text-gray-400 font-mono">
          {{ macroCards.length }} file{{ macroCards.length === 1 ? '' : 's' }}
        </span>
        <button
          type="button"
          class="rounded bg-blue-600 hover:bg-blue-500 disabled:bg-blue-900 px-3 py-1.5 text-xs font-semibold text-white"
          :disabled="isBusy"
          @click="startCreate"
          data-test="macros-create"
        >
          + New macro
        </button>
      </div>
    </div>

    <div v-if="macroCards.length === 0" class="p-6 text-center text-gray-500 text-sm">
      No macros yet. Use <span class="font-mono">+ New macro</span> to create one.
    </div>

    <ul v-else class="p-3 space-y-2">
      <li
        v-for="card in macroCards"
        :key="card.name"
        class="flex items-center justify-between gap-4 rounded-lg border border-gray-700 bg-gray-900/60 p-3"
      >
        <div class="min-w-0">
          <div class="font-mono text-sm font-semibold text-gray-100 truncate">
            🧩 {{ card.name }}.macro
          </div>
          <div class="text-xs text-gray-400">
            {{ formatSize(card.size) }}
          </div>
        </div>
        <div class="flex items-center gap-3 shrink-0">
          <button
            type="button"
            class="rounded bg-blue-600 hover:bg-blue-500 disabled:bg-blue-900 px-3 py-1.5 text-sm font-semibold text-white"
            :disabled="isBusy"
            @click="openEditor(card.name)"
            :data-test="`macros-edit-${card.name}`"
          >
            Edit
          </button>
          <button
            type="button"
            class="rounded bg-red-600 hover:bg-red-500 disabled:bg-red-900 px-3 py-1.5 text-sm font-semibold text-white"
            :disabled="isBusy"
            @click="deleteMacro(card.name)"
            :data-test="`macros-delete-${card.name}`"
          >
            Delete
          </button>
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
            Name
          </label>
          <input
            v-model="createName"
            type="text"
            autofocus
            placeholder="e.g. home_all"
            class="w-full rounded border border-gray-600 bg-gray-900 px-3 py-2 font-mono text-gray-200"
            data-test="macros-create-name"
          />
          <p class="mt-1 text-[11px] text-gray-500">
            Letters, digits, ``_ - .``; 1–64 characters.
          </p>
        </div>
        <p v-if="createError" class="text-xs text-red-400 font-mono" data-test="macros-create-error">
          {{ createError }}
        </p>
        <div class="flex justify-end gap-2">
          <button
            type="button"
            class="rounded bg-gray-600 px-3 py-2 hover:bg-gray-500"
            @click="createOpen = false"
          >
            Cancel
          </button>
          <button
            type="submit"
            class="rounded bg-blue-600 px-3 py-2 font-semibold hover:bg-blue-500 disabled:bg-blue-900"
            :disabled="isBusy || !createName.trim()"
            data-test="macros-create-submit"
          >
            Create
          </button>
        </div>
      </form>
    </div>

    <!-- Edit modal: full-height CodeMirror surface wrapped in
         ``Editor.vue``. ``editorIsDirty`` powers the unsaved-
         changes guard on close. -->
    <div
      v-if="editorOpen"
      class="fixed inset-0 z-50 flex flex-col bg-gray-900"
    >
      <div class="flex items-center justify-between border-b border-gray-700 bg-gray-800 px-4 py-3 shrink-0">
        <div class="flex items-center gap-3">
          <span class="font-mono text-blue-300">
            Editing {{ editorName }}.macro
          </span>
          <span
            v-if="editorIsDirty"
            class="px-1.5 py-0.5 rounded bg-yellow-700/40 text-yellow-200 text-[10px] uppercase tracking-wider"
          >
            unsaved
          </span>
          <span
            v-else
            class="px-1.5 py-0.5 rounded bg-green-700/30 text-green-200 text-[10px] uppercase tracking-wider"
          >
            saved
          </span>
        </div>
        <div class="flex gap-2">
          <button
            type="button"
            class="rounded bg-gray-600 px-4 py-2 font-semibold hover:bg-gray-500"
            @click="closeEditor(false)"
            data-test="macros-editor-close"
          >
            Close
          </button>
          <button
            type="button"
            class="rounded bg-green-600 px-4 py-2 font-semibold hover:bg-green-500 disabled:bg-green-900"
            :disabled="editorSaving || !editorIsDirty || editorLoading"
            @click="saveEditor"
            data-test="macros-editor-save"
          >
            {{ editorSaving ? 'Saving…' : 'Save' }}
          </button>
          <button
            type="button"
            class="rounded bg-blue-600 px-4 py-2 font-semibold hover:bg-blue-500 disabled:bg-blue-900"
            :disabled="editorSaving || editorLoading"
            @click="saveAndCloseEditor"
            data-test="macros-editor-save-close"
          >
            Save &amp; Close
          </button>
        </div>
      </div>
      <div class="min-h-0 flex-1">
        <Editor
          :model-value="editorContent"
          @update:model-value="(value) => (editorContent = value)"
          :filename="`${editorName}.macro`"
          :read-only="editorLoading"
          mode="config"
        />
      </div>
    </div>
  </div>
</template>
