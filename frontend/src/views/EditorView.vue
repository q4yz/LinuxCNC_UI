<script setup>
// Universal editor shell. Reads / writes are delegated entirely
// to `useEditorStore`; this view handles presentation, layout swapping,
// and route-driven data loading.

import { onMounted, ref, computed, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { useConfirm, ModalButtonStyle } from '../core/confirm.js';
import { useUnsavedChangesGuard } from '../router/guards/unsavedChangesGuard.js';

import Editor from '../components/Editor.vue';
import DebugPanel from '../components/DebugPanel.vue';
import UpdateManager from '../components/UpdateManager.vue';
import ProfilesExplorer from '../modules/machineconfig/components/ProfilesExplorer.vue';
import CompilerPanel from '../modules/machineconfig/components/CompilerPanel.vue';
import CompiledOutputViewer from '../modules/machineconfig/components/CompiledOutputViewer.vue';
import DeploymentPanel from '../modules/machineconfig/components/DeploymentPanel.vue';
import ActivePanel from '../modules/machineconfig/components/ActivePanel.vue';

import { useMachineConfigStore } from '../modules/machineconfig/store.js';
import { useEditorStore, resolveEditorMode } from '../stores/editor.js';

const machineConfigStore = useMachineConfigStore();
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

// Close clears the store and routes the user back to the appropriate dashboard.
function closeEditor() {
  editorStore.close();
  const target = editorStore.isGcode ? 'programs' : 'config';
  router.push({ name: target }).catch(err => console.error("Router error on close:", err));
}

// Mirror local edits into the store so `saveFile` uses the latest content.
function handleEditorUpdate(value) {
  editorContent.value = value;
  editorStore.content = value;
}

// Used by ProfilesExplorer to request an edit. This function STRICTLY changes
// the URL. The `watch` block above detects the URL change and loads the file.
function openEditor(path) {
  router.push({ name: 'config', params: { filename: path } })
        .catch(err => console.error("Router error on open:", err));
}

onMounted(async () => {
  await loadFromSource();
  void machineConfigStore.loadAll();
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

  <div v-else class="grid grid-cols-1 gap-6 pb-8 xl:grid-cols-12">
    <section class="space-y-6 xl:col-span-4">
      <UpdateManager />
      <DebugPanel />
    </section>

    <section class="space-y-6 xl:col-span-8">
      <CompilerPanel />

      <div class="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <ProfilesExplorer @edit="openEditor" />

        <div class="space-y-6">
          <CompiledOutputViewer />
          <DeploymentPanel />
        </div>
      </div>

      <ActivePanel />
    </section>
  </div>
</template>