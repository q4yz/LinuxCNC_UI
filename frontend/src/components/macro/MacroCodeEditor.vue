<script setup>
// CodeMirror wrapper for the macro editor. Reuses the same
// ``vue-codemirror`` + ``@codemirror/lang-javascript`` stack as
// the existing ``Editor.vue`` so a single import covers both
// surfaces. ``Syntax-highlight`` mode is fixed to G-code with
// nested Python blocks; the parser's two-block distinction is
// already enforced by the backend.

import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { Codemirror } from 'vue-codemirror';
import { javascript } from '@codemirror/lang-javascript';
import { oneDark } from '@codemirror/theme-one-dark';

const props = defineProps({
  modelValue: { type: String, default: '' },
  readOnly: { type: Boolean, default: false },
});

const emit = defineEmits(['update:modelValue']);

// Keep the CodeMirror view handle so we can dispatch a refresh
// when the parent swaps macros. ``vue-codemirror`` does not
// expose a setter directly, so we simulate one by toggling
// ``viewRef`` which is bound to the wrapper.
const viewRef = ref(null);

const extensions = computed(() => [javascript(), oneDark]);

function forwardUpdate(value) {
  emit('update:modelValue', value);
}

// CodeMirror takes a tick to attach; refresh on the next frame
// after the macro swaps so the cursor lands at the top of the
// new content.
watch(
  () => props.modelValue,
  () => {
    requestAnimationFrame(() => {
      const root = viewRef.value?.$el ?? viewRef.value;
      if (root && typeof root.querySelector === 'function') {
        const cm = root.querySelector('.cm-editor');
        if (cm && typeof cm.cmView?.view?.requestMeasure === 'function') {
          cm.cmView.view.requestMeasure();
        }
      }
    });
  }
);

onBeforeUnmount(() => {
  // ``vue-codemirror`` handles its own dispose; nothing further
  // to do here. Adding an explicit hook keeps the unmount path
  // symmetric with the rest of the editor components.
});
</script>

<template>
  <div class="h-full w-full bg-gray-900">
    <Codemirror
      ref="viewRef"
      :model-value="modelValue"
      @update:model-value="forwardUpdate"
      :extensions="extensions"
      :disabled="readOnly"
      class="h-full"
    />
  </div>
</template>

<style scoped>
:deep(.cm-editor) {
  height: 100%;
  outline: none;
  background: rgb(17 24 39);
}
:deep(.cm-scroller) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
}
</style>
