<script setup>
// "Dumb" CodeMirror wrapper. Receives ``modelValue`` and emits
// updates; the parent (``EditorView``) owns all file I/O through
// ``useEditorStore``. This component is a pure presentation layer —
// it does not fetch, save, or even know what file it is editing.
//
// Note on the API surface: the component only declares the
// ``update:modelValue`` emit. Earlier iterations also declared
// ``close`` and ``save`` emits but nothing fired them — the
// parent (``EditorView``) handles those actions via its own
// ``@click`` handlers on the header buttons. Keeping the API
// minimal avoids the dead-code smell that future maintainers
// would chase.

import { computed } from 'vue'
import { Codemirror } from 'vue-codemirror'
import { javascript } from '@codemirror/lang-javascript'
import { oneDark } from '@codemirror/theme-one-dark'
import { ini } from '../utils/codemirror-lang-ini'
import { hal } from '../utils/codemirror-lang-hal'
import { gcode } from '../utils/codemirror-lang-gcode'

const props = defineProps({
  filename: { type: String, required: true },
  modelValue: { type: String, default: '' },
  readOnly: { type: Boolean, default: false },
  /**
   * Editor mode. Controls which CodeMirror language extension is
   * loaded:
   *   ``"profile"`` / ``"config"`` / ``"ini"`` / ``"cfg"`` —
   *     Klipper/LinuxCNC INI-style configuration. Highlighted via
   *     the ``properties`` StreamLanguage.
   *   ``"hal"`` — LinuxCNC HAL files. Highlighted with a C-like
   *     grammar and HAL keywords.
   *   ``"gcode"`` / ``"ngc"`` — G-code (RS-274 / LinuxCNC).
   *   ``"js"`` / ``"javascript"`` — JavaScript syntax highlighting.
   *   ``"json"`` — JSON syntax highlighting.
   *   ``"text"`` — Plain text fallback.
   */
  mode: { type: String, default: 'config' }
})

const emit = defineEmits(['update:modelValue'])

// Pick the CodeMirror extensions for the active mode. ``oneDark``
// is always present so the surrounding dark theme is consistent
// across file types. A language pack is added per mode so that
// tokens actually get coloured — a theme alone cannot highlight
// plain text.
const editorExtensions = computed(() => {
  const m = (props.mode || 'config').toLowerCase()
  switch (m) {
    case 'js':
    case 'javascript':
      return [javascript(), oneDark]
    case 'json':
      return [javascript({ json: true }), oneDark]
    case 'config':
      return [ini(), oneDark]
    case 'hal':
      return [hal(), oneDark]
    case 'gcode':
      return [gcode(), oneDark]
    default:
      return [oneDark]
  }
})

// Forward CodeMirror's update event directly to the parent. No
// local state, no debouncing — the parent controls cadence.
function forwardUpdate(value) {
  emit('update:modelValue', value)
}
</script>

<template>
  <div class="flex h-full min-h-0 w-full flex-col bg-gray-900 text-gray-200">
    <!-- ``min-h-0`` is the key CSS property that lets the inner
         scroller overflow inside a flex column without breaking
         the page layout. Loading state lives in the parent. -->
    <div class="editor-shell min-h-0 flex-1 overflow-hidden">
      <Codemirror
        :model-value="modelValue"
        @update:model-value="forwardUpdate"
        :extensions="editorExtensions"
        :disabled="readOnly"
        class="editor-codemirror"
      />
    </div>
  </div>
</template>

<style scoped>
/* ``h-full`` propagates down through the flex column so the
   CodeMirror scroller fills the available height. ``min-h-0``
   defeats the default ``min-height: auto`` that flex items
   inherit, which is what breaks scrolling inside a flex parent. */
.editor-shell {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.editor-codemirror {
  height: 100%;
  width: 100%;
  display: flex;
  flex-direction: column;
}

:deep(.cm-editor) {
  height: 100%;
  width: 100%;
  outline: none;
  background: rgb(17 24 39);
  overflow: auto;
}

:deep(.cm-scroller) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
}
</style>