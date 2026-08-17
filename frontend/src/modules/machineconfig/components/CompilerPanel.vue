<script setup>
// CompilerPanel — picks the active Configuration Compiler and
// triggers a compile on the currently selected profile.
//
// The panel pairs with the inline "Compile" buttons in the
// :class:`ProfilesExplorer` — clicking one there also fires
// ``store.compile(profilePath)``, so this panel is mostly for
// operators who want to (re)compile via the dropdown instead of
// per-file.

import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useMachineConfigStore } from "../store";

const store = useMachineConfigStore();
const { compilers, selectedCompilerId, selectedCompiler, selectedProfilePath, isBusy } =
  storeToRefs(store);

const profileLabel = computed(() => selectedProfilePath.value || "(no profile selected)");

async function onCompile() {
  if (!selectedProfilePath.value) {
    // eslint-disable-next-line no-alert
    window.alert("Select a profile in the explorer first.");
    return;
  }
  await store.compile(selectedProfilePath.value);
}
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden">
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        <span class="mr-2">⚙️</span> Configuration Compiler
      </h2>
    </div>

    <div class="p-4 space-y-4">
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
        <div class="md:col-span-2">
          <label class="block text-xs uppercase tracking-wider text-gray-400 mb-1">
            Active Compiler
          </label>
          <select
            v-model="selectedCompilerId"
            class="w-full rounded bg-gray-900 border border-gray-600 text-gray-200 px-3 py-2"
          >
            <option disabled value="">Select a compiler...</option>
            <option v-for="compiler in compilers" :key="compiler.id" :value="compiler.id">
              {{ compiler.title }} <span class="text-gray-500">({{ compiler.id }})</span>
            </option>
          </select>
          <p
            v-if="selectedCompiler"
            class="mt-1 text-[11px] text-gray-400 font-mono"
          >
            Source marker: <code>{{ selectedCompiler.source_marker || "(none)" }}</code>
          </p>
        </div>
        <button
          type="button"
          :disabled="isBusy || !selectedCompiler || !selectedProfilePath"
          class="w-full px-3 py-2 rounded font-semibold bg-blue-600 hover:bg-blue-500 disabled:bg-blue-900 disabled:cursor-not-allowed"
          @click="onCompile"
        >
          {{ isBusy ? 'Compiling…' : 'Compile Selected' }}
        </button>
      </div>

      <p class="text-xs text-gray-400">
        Active profile:
        <code class="text-gray-300 font-mono">{{ profileLabel }}</code>
      </p>
    </div>
  </div>
</template>