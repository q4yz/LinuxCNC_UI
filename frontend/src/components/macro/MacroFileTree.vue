<script setup>
// Sidebar list of available macros. The parent
// (``MacroEditor.vue``) passes the macro list and the currently
// selected name; this component emits ``select`` events so the
// view stays in charge of the actual fetching / loading.

import { computed } from 'vue';

const props = defineProps({
  macros: { type: Array, required: true },
  selectedName: { type: String, default: '' },
  isLoading: { type: Boolean, default: false },
});

const emit = defineEmits(['select', 'new']);

const sorted = computed(() => {
  return [...props.macros].sort((a, b) => {
    return (a.name || '').localeCompare(b.name || '');
  });
});

function pick(name) {
  emit('select', name);
}
</script>

<template>
  <div class="flex flex-col h-full bg-gray-900 border-r border-gray-700 w-64 shrink-0">
    <div class="flex items-center justify-between px-4 py-3 border-b border-gray-700">
      <h3 class="text-xs font-semibold uppercase tracking-wider text-gray-300">
        Files
      </h3>
      <button
        type="button"
        class="px-2 py-1 text-xs bg-blue-600 hover:bg-blue-500 rounded text-white font-semibold"
        @click="emit('new')"
      >
        New
      </button>
    </div>

    <div class="flex-1 overflow-y-auto">
      <p v-if="isLoading && macros.length === 0" class="px-4 py-2 text-xs text-gray-500 italic">
        Loading…
      </p>
      <p v-else-if="macros.length === 0" class="px-4 py-2 text-xs text-gray-500 italic">
        No macros yet. Click "New" to start.
      </p>
      <ul v-else class="divide-y divide-gray-800">
        <li v-for="macro in sorted" :key="macro.name">
          <button
            type="button"
            class="w-full text-left px-4 py-2 text-sm font-mono transition-colors"
            :class="selectedName === macro.name
              ? 'bg-blue-600/40 text-white'
              : 'text-gray-300 hover:bg-gray-800'"
            @click="pick(macro.name)"
          >
            {{ macro.name }}
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>
