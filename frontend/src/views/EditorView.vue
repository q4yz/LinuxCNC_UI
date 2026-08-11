<script setup>
// Universal editor shell. Editor-only: the surface that used to
// render the machineconfig panel grid when no filename was set
// moved to ``MachineConfigView.vue`` (mounted at ``/machineconfig``).
// EditorView now renders the editor overlay only when a filename
// is present in ``route.params``; otherwise it renders a small
// empty-state prompt pointing operators at the new ``Machine
// Config`` route so deep-links like ``/config/`` still get a sane
// landing page instead of nothing.

import { onMounted, ref, computed, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { useConfirm, ModalButtonStyle } from '../core/confirm.js';
import { useUnsavedChangesGuard } from '../router/guards/unsavedChangesGuard.js';

import Editor from '../components/Editor.vue';
import { useEditorStore, resolveEditorMode } from '../stores/editor.js';

const editorStore = useEditorStore();
const route = useRoute();
const router = useRouter();

useUnsavedChangesGuard(() => editorStore.isDirty);

// Local mirror of the editor content so the v-model works in
// both directions (CodeMirror ↔ Pinia). The store still owns the canonical copy.
const editorContent = ref('');

// --- Mode + path derivation -------------------------------------- //
//
// ``resolveEditorMode`` (from the store) is the single source of
// truth for the extension → mode map. It covers gcode, profile, JS,
// TS, JSON, Python, YAML, Markdown, Shell, HTML, CSS, XML, etc.
// — see the store for the full table. The mode is purely for
// syntax highlighting and UI hints; the store routes I/O by the
// file's path, not by its extension.

function hydratePath() {
  let param = route.params?.filename;
  // Handle catch-all routes (.*) where Vue Router might return an array
  if (Array.isArray(param)) param = param.join('/');

  if (typeof param === 'string' && param.length > 0) {
    return decodeURIComponent(param);
  }
  return editorStore.filename || '';
}

const editorPath = computed(() => hydratePath());
const editorMode = computed(() =>
  resolveEditorMode(editorPath.value || editorStore.filename)
);

// --- Loading logic ----------------------------------------------- //

async function loadFromSource() {
  const targetPath = editorPath.value;
  if (!targetPath) return;

  // Mirror the store's view of the active file into our local
  // ref so the editor sees the latest content immediately.
  if (editorStore.filename === targetPath && editorStore.hasContent) {
    editorContent.value = editorStore.content;
    return;
  }

  // The store is the single source of truth for I/O.
  editorStore.open(targetPath, false, editorMode.value, '');
  try {
    await editorStore.loadFile(targetPath, editorMode.value);
    editorContent.value = editorStore.content;
  } catch (error) {
    console.error("Failed to load file content:", error);
    editorContent.value = '';
  }
}

// The URL is the single source of truth. When the route parameter changes,
// fetch the new file.
watch(
  () => route.params.filename,
  async () => {
    if (editorStore.isDirty && editorStore.filename !== editorPath.value) {
      const shouldLeave = await useConfirm({
        title: "Ungespeicherte Änderungen",
        question: "Möchten Sie diese Seite wirklich verlassen?",
        description: "Alle nicht gespeicherten Eingaben gehen verloren und können nicht wiederhergestellt werden.",
        confirmButtonText: "Seite verlassen",
        confirmButtonStyle: ModalButtonStyle.DANGER,
        rejectButtonText: "Hier bleiben",
        showDismissCrossButton: false,
      });
      if (!shouldLeave) {
        await router.replace({ name: route.name, params: { filename: editorStore.filename } });
        return;
      }
    }
    await loadFromSource();
  }
);

// --- Save & Close Handlers --------------------------------------- //

async function saveEditor() {
  if (!editorPath.value) return;
  await editorStore.saveFile(editorPath.value, editorContent.value, editorMode.value);
}

async function saveAndCloseEditor() {
  await saveEditor();
  closeEditor();
}

async function confirmClose() {
  const shouldClose = !editorStore.isDirty || await useConfirm({
    title: "Ungespeicherte Änderungen",
    question: "Are you sure you want to close? Any unsaved changes will be lost.",
    confirmButtonText: "Close",
    confirmButtonStyle: ModalButtonStyle.DANGER,
    rejectButtonText: "Cancel",
    showDismissCrossButton: false,
  });
  if (shouldClose) closeEditor();
}

// Close clears the store and routes the operator back to the
// surface that owns the file kind. G-code files land on the
// programs dashboard; everything else (profiles, .cfg / .ini /
// .conf, .macro, M-code, …) lands on the machineconfig surface
// at /machineconfig. The legacy ``name: 'config'`` route is now
// editor-only so navigating to it without a filename would loop.
function closeEditor() {
  editorStore.close();
  const target = editorStore.isGcode ? 'programs' : 'machineconfig';
  router.push({ name: target }).catch(err => console.error("Router error on close:", err));
}

// Mirror local edits into the store so `saveFile` uses the latest content.
function handleEditorUpdate(value) {
  editorContent.value = value;
  editorStore.content = value;
}

onMounted(async () => {
  await loadFromSource();
});
</script>

<template>
  <div v-if="editorPath" class="fixed inset-0 z-50 flex flex-col bg-gray-900">
    <div class="flex items-center justify-between border-b border-gray-700 bg-gray-800 px-4 py-3">
      <span class="font-mono text-blue-300">Editing {{ editorPath }}</span>
      <div class="flex gap-2">
        <button type="button" class="rounded bg-gray-600 px-4 py-2 font-semibold hover:bg-gray-500" @click="confirmClose">Close</button>
        <button type="button" class="rounded bg-blue-600 px-4 py-2 font-semibold hover:bg-blue-500" @click="saveAndCloseEditor">Save &amp; Close</button>
        <button type="button" class="rounded bg-green-600 px-4 py-2 font-semibold hover:bg-green-500" @click="saveEditor">Save</button>
      </div>
    </div>

    <!-- `min-h-0` + `flex-1` lets the editor scroll inside the
         fixed-position overlay without breaking the page layout. -->
    <div class="min-h-0 flex-1">
      <Editor
        :model-value="editorContent"
        @update:model-value="handleEditorUpdate"
        :filename="editorPath"
        :read-only="editorStore.readOnly"
        :mode="editorMode"
      />
    </div>
  </div>

  <!-- No-filename fallback: the machineconfig surface moved to
       /machineconfig. Render a small pointer so deep-links like
       /config/ (no filename) land somewhere sensible instead of
       an empty main slot. The full panel grid lives in
       ``MachineConfigView``. -->
  <div v-else class="flex h-full items-center justify-center p-8 text-center text-gray-400">
    <div class="space-y-3">
      <p class="text-sm">
        Pick a file from
        <button
          type="button"
          class="text-blue-400 underline hover:text-blue-300"
          @click="router.push({ name: 'programs' })"
        >
          G-Code Files
        </button>
        or open
        <button
          type="button"
          class="text-blue-400 underline hover:text-blue-300"
          @click="router.push({ name: 'machineconfig' })"
        >
          Machine Config
        </button>
        to start editing.
      </p>
    </div>
  </div>
</template>
