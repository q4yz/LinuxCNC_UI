<script setup>
// Macro editor view (issue #7). Layout:
//
//   ┌─────────────────────────────────────────────┐
//   │  Toolbar (Save / Run / Delete / New)        │
//   ├─────────────┬───────────────────────────────┤
//   │             │                               │
//   │  File Tree  │        CodeMirror            │
//   │             │                               │
//   │             ├───────────────────────────────┤
//   │             │  Console (log output)         │
//   └─────────────┴───────────────────────────────┘
//
// All state lives in the ``useMacroStore`` Pinia store; this
// view is composition only.

import { computed, onMounted } from 'vue';
import { storeToRefs } from 'pinia';

import MacroFileTree from '../components/macro/MacroFileTree.vue';
import MacroCodeEditor from '../components/macro/MacroCodeEditor.vue';
import MacroConsole from '../components/macro/MacroConsole.vue';
import MacroEditorToolbar from '../components/macro/MacroEditorToolbar.vue';

import { useMacroStore } from '../stores/macros';
import { DEFAULT_MACROS } from '../config/gcodes';

const store = useMacroStore();
const {
  macros,
  selectedName,
  content,
  logs,
  running,
  saving,
  loading,
  dirty,
  error,
  lastResult,
} = storeToRefs(store);

const traceback = computed(() => lastResult.value?.error || '');

onMounted(async () => {
  await store.loadMacros();
});

async function onSelect(name) {
  await store.select(name);
}

async function onSave() {
  await store.save();
}

async function onRun() {
  if (!selectedName.value) return;
  await store.run(selectedName.value);
}

async function onDelete() {
  if (!selectedName.value) return;
  if (!window.confirm(`Delete macro "${selectedName.value}"? This cannot be undone.`)) {
    return;
  }
  await store.remove(selectedName.value);
}

function onNew() {
  const template = DEFAULT_MACROS.probe_grid;
  store.newFromTemplate(template);
}

function onContentUpdate(value) {
  store.updateContent(value);
}

function onClearLogs() {
  store.clearLogs();
}
</script>

<template>
  <div class="h-full w-full flex flex-col bg-gray-900 text-gray-100">
    <MacroEditorToolbar
      :active-name="selectedName || ''"
      :dirty="dirty"
      :saving="saving"
      :running="running"
      @save="onSave"
      @run="onRun"
      @delete="onDelete"
      @new="onNew"
    />

    <div class="flex flex-1 min-h-0">
      <MacroFileTree
        :macros="macros"
        :selected-name="selectedName || ''"
        :is-loading="loading"
        @select="onSelect"
        @new="onNew"
      />

      <div class="flex-1 flex flex-col min-w-0">
        <div class="flex-1 min-h-0">
          <MacroCodeEditor
            :model-value="content"
            @update:model-value="onContentUpdate"
            :read-only="running"
          />
        </div>

        <MacroConsole
          :logs="logs"
          :error="traceback || error"
          :running="running"
          @clear="onClearLogs"
        />
      </div>
    </div>
  </div>
</template>
