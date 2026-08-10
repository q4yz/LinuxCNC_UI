<script setup>
// Dashboard M-code panel. Lists LinuxCNC's custom-M-code files in
// the canonical ``M100..M199`` range from
// ``<repo>/machine_config/m_codes/``. Each row carries name + size
// + Edit / Delete; there's no "Run" button because the
// interpreter dispatches M-codes itself on ``M<num>`` MDI calls.
//
// Editing opens the universal editor with the bare ``M<num>``
// name; the universal editor's ``isProfilePath`` recognises the
// ``^M1\d{2}$`` shape and routes the read/write to the
// machineconfig router's ``/m-codes/...`` endpoints.
//
// The store is loaded lazily on mount; the listing starts empty
// and renders a skeleton-style empty state until the first
// refresh completes.

import { computed, onMounted } from "vue";
import { storeToRefs } from "pinia";

import { useMacrosStore, MACRO_KIND } from "../store.js";

const store = useMacrosStore();
const { isBusy, mcodeFiles } = storeToRefs(store);

// Reads the mcode-only container directly. Each per-kind listing
// is independent in the store so ``storeToRefs(mcodeFiles)`` stays
// reactive without clobbering siblings on load.
const sorted = computed(() =>
  [...mcodeFiles.value].sort((a, b) => a.name.localeCompare(b.name)),
);

onMounted(async () => {
  await store.loadList(MACRO_KIND.MCODE);
});

async function onRefresh() {
  await store.loadList(MACRO_KIND.MCODE);
}

async function onDelete(name) {
  await store.deleteMacro(MACRO_KIND.MCODE, name);
}
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden">
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex justify-between items-center">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        <span class="mr-2">⚙️</span> M-Codes
      </h2>
      <div class="flex items-center gap-3">
        <span class="text-xs text-gray-400 font-mono">
          {{ sorted.length }} M-code{{ sorted.length === 1 ? '' : 's' }}
        </span>
        <button
          type="button"
          class="px-2 py-1 text-xs rounded bg-gray-600 hover:bg-gray-500 text-white disabled:opacity-50"
          :disabled="isBusy"
          @click="onRefresh"
        >
          ↻ Refresh
        </button>
      </div>
    </div>

    <div v-if="sorted.length === 0" class="p-6 text-center text-gray-500 text-sm">
      <p>No M-codes yet.</p>
      <p class="mt-1 text-xs text-gray-600">
        Add one in <span class="font-mono">Machine Config</span> →
        <span class="font-mono">Macros</span> → <span class="font-mono">M-codes</span>.
      </p>
    </div>

    <ul v-else class="p-3 space-y-2">
      <li
        v-for="row in sorted"
        :key="row.name"
        class="flex items-center justify-between gap-4 rounded-lg border border-gray-700 bg-gray-900/60 p-3"
      >
        <div class="min-w-0">
          <div class="font-mono text-sm font-semibold text-gray-100 truncate flex items-center gap-2">
            <span class="text-yellow-300">M</span><span>{{ row.name.slice(1) }}</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-yellow-700/40 text-yellow-200 uppercase tracking-wider">
              M-code
            </span>
          </div>
          <div class="text-xs text-gray-500">
            {{ row.size_bytes }} bytes
          </div>
        </div>
        <div class="flex items-center gap-3 shrink-0">
          <a
            class="rounded bg-blue-600 hover:bg-blue-500 px-3 py-1.5 text-sm font-semibold text-white"
            :href="`#/config/${encodeURIComponent(row.name)}`"
            @click.prevent="$router.push({ name: 'config', params: { filename: row.name } })"
          >
            Edit
          </a>
          <button
            type="button"
            class="rounded bg-red-600 hover:bg-red-500 disabled:bg-red-900 px-3 py-1.5 text-sm font-semibold text-white"
            :disabled="isBusy"
            @click="onDelete(row.name)"
          >
            Delete
          </button>
        </div>
      </li>
    </ul>
  </div>
</template>
