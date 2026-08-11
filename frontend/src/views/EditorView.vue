<script setup>
// Universal editor shell — the ONLY mount point for ``<Editor>``
// anywhere in the app (issue #132).
//
// Contract
// --------
// The view consumes three query-string inputs:
//
//     /editor?source=profiles&name=klipper.cfg&readOnly=false
//     /editor?source=active&name=hardware.json&readOnly=true
//     /editor?source=staged&name=machine.cfg&readOnly=true
//     /editor?source=m_codes&name=M101&readOnly=false
//     /editor?source=programs&name=foo.gcode&readOnly=false
//     /editor?source=macros&name=my_macro&readOnly=false
//
// ``source`` selects the dispatch branch in :func:`useEditorStore`
// (the store is the only place that knows the backend surface).
// ``name`` is the filename, or path-within-profiles. ``readOnly`` is
// optional — ``active`` and ``staged`` default to read-only.
//
// The component never reads the filename extension to decide
// routing; that was the bug behind the ``.txt`` profile miss. The
// ``source`` query param drives everything; the extension only
// decides CodeMirror's syntax overlay.

import { onBeforeUnmount, onMounted, ref, computed, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { useConfirm, ModalButtonStyle } from '../core/confirm.js';
import {
  useUnsavedChangesGuard,
  UNSAVED_PROMPT,
} from '../router/guards/unsavedChangesGuard.js';

import Editor from '../components/Editor.vue';
import {
  useEditorStore,
  EDITOR_SOURCES,
  sourceLabel,
} from '../stores/editor.js';
import { openInEditor } from '../helpers/openInEditor.js';

const editorStore = useEditorStore();
const route = useRoute();
const router = useRouter();

useUnsavedChangesGuard(() => editorStore.isDirty);

// Local mirror of the editor content so the v-model works in
// both directions (CodeMirror ↔ Pinia). The store still owns the
// canonical copy.
const editorContent = ref('');

// --- Query → store identity -------------------------------------- //
//
// Pull the (source, name, readOnly) tuple out of the URL query and
// hand it to the store. The store rejects invalid sources with a
// loud ``Error``; we convert that into a friendly empty-state
// fallback so a typo in a bookmarked URL does not crash the shell.

const SOURCES = Object.values(EDITOR_SOURCES)

const currentSource = computed(() => {
  const raw = route.query?.source
  const value = Array.isArray(raw) ? raw[0] : raw
  return typeof value === 'string' && SOURCES.includes(value) ? value : ''
})

const currentName = computed(() => {
  const raw = route.query?.name
  const value = Array.isArray(raw) ? raw[0] : raw
  return typeof value === 'string' && value.length > 0 ? value : ''
})

const currentReadOnly = computed(() => {
  const raw = route.query?.readOnly
  const value = Array.isArray(raw) ? raw[0] : raw
  if (typeof value !== 'string') return false
  return value === 'true' || value === '1'
})

// Whether the URL has the minimum required params. The empty-state
// fallback below renders when this is false.
const hasValidTarget = computed(() => currentSource.value !== '' && currentName.value !== '')

// --- Loading ----------------------------------------------------- //

async function loadFromRoute() {
  if (!hasValidTarget.value) return

  // Re-mounting the same file is a no-op (back-button, refresh).
  if (
    editorStore.source === currentSource.value &&
    editorStore.name === currentName.value &&
    editorStore.readOnly === currentReadOnly.value
  ) {
    return
  }

  editorStore.open({
    source: currentSource.value,
    name: currentName.value,
    readOnly: currentReadOnly.value,
  })
  try {
    await editorStore.loadFile()
    editorContent.value = editorStore.content
  } catch (error) {
    console.error("Failed to load file content:", error)
    editorContent.value = ''
  }
}

// --- Route watcher ----------------------------------------------- //
//
// The URL is the single source of truth. Re-load on every change
// after prompting about unsaved work the way the legacy shell did.

watch(
  () => [currentSource.value, currentName.value, currentReadOnly.value],
  async ([nextSource, nextName, nextReadOnly]) => {
    if (editorStore.isDirty && editorStore.name !== nextName) {
      // Same copy as the URL-leave guard uses — both prompts
      // render through ``UNSAVED_PROMPT``.
      const shouldLeave = await useConfirm({
        title: UNSAVED_PROMPT.title,
        question: UNSAVED_PROMPT.question,
        confirmButtonText: UNSAVED_PROMPT.confirmText,
        confirmButtonStyle: ModalButtonStyle.DANGER,
        rejectButtonText: UNSAVED_PROMPT.rejectText,
        rejectButtonStyle: ModalButtonStyle.SECONDARY,
        showDismissCrossButton: false,
      });
      if (!shouldLeave) {
        await router.replace({
          name: 'editor',
          query: {
            source: editorStore.source,
            name: editorStore.name,
            readOnly: editorStore.readOnly ? 'true' : 'false',
          },
        });
        return;
      }
    }
    // Trigger the loader; harmless when the params didn't actually
    // change (``loadFromRoute`` short-circuits).
    void nextSource; void nextReadOnly
    await loadFromRoute()
  },
)

// --- Save / Close handlers -------------------------------------- //

async function promptUnsavedClose() {
  // Read-only sources cannot have dirty content, so we never
  // prompt for them — ``Editor.vue`` disables editing when
  // ``readOnly`` is true.
  if (!editorStore.isDirty) return true
  return useConfirm({
    title: UNSAVED_PROMPT.title,
    question: UNSAVED_PROMPT.question,
    confirmButtonText: UNSAVED_PROMPT.confirmText,
    confirmButtonStyle: ModalButtonStyle.DANGER,
    rejectButtonText: UNSAVED_PROMPT.rejectText,
    rejectButtonStyle: ModalButtonStyle.SECONDARY,
    showDismissCrossButton: false,
  })
}

async function saveEditor() {
  if (!hasValidTarget.value) return
  await editorStore.saveFile(editorContent.value)
}

async function saveAndCloseEditor() {
  await saveEditor()
  closeEditor()
}

async function confirmClose() {
  if (await promptUnsavedClose()) closeEditor()
}

// Close clears the store and routes the operator back to the
// surface that owns the file kind. Programs land on the programs
// dashboard; profiles and macros land on the machineconfig surface;
// everything else (active/staged/m_codes) goes back to machineconfig
// too since that view owns both the deployed artifact viewer and
// the M-code manager.
function closeEditor() {
  editorContent.value = ''
  editorStore.close()
  const target = currentSource.value === EDITOR_SOURCES.PROGRAMS ? 'programs' : 'machineconfig'
  router.push({ name: target }).catch(err => console.error("Router error on close:", err))
}

// Mirror local edits into the store so ``saveFile`` uses the
// latest content.
function handleEditorUpdate(value) {
  editorContent.value = value
  editorStore.content = value
}

// --- Keyboard shortcut: Ctrl+S / Cmd+S triggers save ------------ //
//
// ``EditorView`` is a fixed-position overlay so the browser's
// built-in save dialog never appears. We intercept the chord at
// the document level while the overlay is mounted so it works
// regardless of focus (CodeMirror, header button, anywhere inside
// the overlay). ``isDirty`` and ``readOnly`` short-circuit so we
// never persist noise.
function onSaveShortcut(event) {
  const isSaveChord = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's'
  if (!isSaveChord) return
  event.preventDefault()
  if (editorStore.readOnly || !editorStore.isDirty) return
  void saveEditor()
}

onMounted(async () => {
  await loadFromRoute()
  document.addEventListener('keydown', onSaveShortcut)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onSaveShortcut)
  // Make sure the local mirror is cleared when the operator
  // navigates away via a route other than ``closeEditor`` (back
  // button, ``useUnsavedChangesGuard`` accept, etc.). The store
  // already cleared itself; the ref must follow.
  editorContent.value = ''
})
</script>

<template>
  <div v-if="hasValidTarget" class="fixed inset-0 z-50 flex flex-col bg-gray-900">
    <div class="flex items-center justify-between border-b border-gray-700 bg-gray-800 px-4 py-3">
      <span class="font-mono text-blue-300">
        Editing {{ currentName }} ({{ sourceLabel(currentSource) }})
      </span>
      <div class="flex gap-2">

        <!-- ``Save`` and ``Save & Close`` are read-write affordances.
             When the store opens a read-only source (``active``,
             ``staged``, or any source the caller pinned read-only),
             both buttons are hidden so the operator does not see
             a greyed-out control they cannot use. -->
        <template v-if="!editorStore.readOnly">
          <button type="button" class="rounded bg-blue-600 px-4 py-2 font-semibold hover:bg-blue-500" @click="saveAndCloseEditor">Save &amp; Close</button>
          <button
            type="button"
            class="rounded bg-green-600 px-4 py-2 font-semibold hover:bg-green-500 disabled:bg-green-900"
            :disabled="!editorStore.isDirty"
            @click="saveEditor"
          >
            Save
          </button>
        </template>
        <button type="button" class=" rounded bg-gray-600 px-4 py-2 font-semibold hover:bg-gray-500 mr-30" @click="confirmClose">Close</button>
      </div>
    </div>

    <!-- ``min-h-0`` + ``flex-1`` lets the editor scroll inside the
         fixed-position overlay without breaking the page layout. -->
    <div class="min-h-0 flex-1">
      <Editor
        :model-value="editorContent"
        @update:model-value="handleEditorUpdate"
        :filename="currentName"
        :read-only="editorStore.readOnly"
        :mode="editorStore.syntaxMode"
      />
    </div>
  </div>

  <!-- No-target fallback: the editor only mounts with a (source,
       name) pair. Render a small pointer so deep-links like
       ``/editor`` (no query) land somewhere sensible instead of an
       empty main slot. -->
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