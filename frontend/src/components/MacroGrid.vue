<script setup>
// Dashboard widget rendering one button per available macro
// (issue #7). Mainsail-inspired layout: a responsive grid that
// wraps gracefully on touchscreens, with a single click firing
// the macro through the Pinia store. Transients (running spinner,
// last-run status) live entirely in the local component so the
// store stays unaware of short-lived UI state.

import { onMounted, ref } from 'vue';
import { storeToRefs } from 'pinia';

import { useMacroStore } from '../stores/macros';

const store = useMacroStore();
const { macros, isLoading, error, running } = storeToRefs(store);

// Track which macro produced the last run result so the operator
// can see at a glance whether the most recent click succeeded.
const lastRunName = ref(null);
const lastRunOk = ref(null);

onMounted(async () => {
  await store.loadMacros();
});

async function invoke(name) {
  lastRunName.value = name;
  lastRunOk.value = null;
  const result = await store.run(name);
  if (result) {
    lastRunOk.value = result.ok;
  } else {
    lastRunOk.value = false;
  }
  // Clear the indicator after a few seconds so the grid is not
  // permanently tinted green / red.
  setTimeout(() => {
    if (lastRunName.value === name) {
      lastRunName.value = null;
      lastRunOk.value = null;
    }
  }, 4000);
}

function statusClass(name) {
  if (lastRunName.value !== name) return '';
  if (lastRunOk.value === true) return 'bg-green-700/60 border-green-500 text-green-100';
  if (lastRunOk.value === false) return 'bg-red-700/60 border-red-500 text-red-100';
  return 'bg-blue-700/60 border-blue-400 text-blue-100';
}
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl p-4 flex flex-col space-y-3">
    <header class="flex items-center justify-between">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">
        Macros
      </h2>
      <span v-if="running" class="text-xs text-blue-300">Running…</span>
    </header>

    <p v-if="isLoading && macros.length === 0" class="text-xs text-gray-500 italic">
      Loading macros…
    </p>

    <p v-else-if="macros.length === 0" class="text-xs text-gray-500 italic">
      No macros available. Create one in the
      <router-link to="/macros" class="underline text-blue-400">Macro Editor</router-link>.
    </p>

    <p v-else-if="error" class="text-xs text-red-400">
      {{ error }}
    </p>

    <div
      v-if="macros.length > 0"
      class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3"
      data-test="macro-grid"
    >
      <button
        v-for="macro in macros"
        :key="macro.name"
        type="button"
        class="border rounded-lg py-4 px-3 text-sm font-semibold transition-colors flex items-center justify-center text-center break-words min-h-[3.5rem]"
        :class="statusClass(macro.name) || 'bg-gray-700 hover:bg-blue-600 border-gray-600 text-gray-100'"
        :disabled="running"
        @click="invoke(macro.name)"
        :data-test="`macro-button-${macro.name}`"
      >
        <span class="font-mono">{{ macro.name.replace(/\.macro$/, '') }}</span>
      </button>
    </div>
  </div>
</template>
