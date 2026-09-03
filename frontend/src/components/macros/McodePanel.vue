<script setup lang="ts">
// Dashboard M-code panel. Lists LinuxCNC's custom-M-code files in
// the canonical ``M100..M199`` range from
// ``<repo>/machine_config/m_codes/``. Each row carries name + size
// + Edit / Delete; there's no "Run" button because the
// interpreter dispatches M-codes itself on ``M<num>`` MDI calls.
//
// Editing pushes ``/editor?source=m_codes&name=<token>`` via the
// shared :func:`openInEditor` helper; the universal editor's
// source-driven dispatch routes the read/write to the
// machineconfig router's ``/m-codes/...`` endpoints.
//
// The store is loaded lazily on mount; the listing starts empty
// and renders a skeleton-style empty state until the first
// refresh completes.

import { computed, onMounted } from "vue";
import { storeToRefs } from "pinia";

import { useMacrosStore, MACRO_KIND } from "../../stores/macrosStore";
import { openInEditor } from "../../helpers/openInEditor";
import type { MacroEntry } from "../../stores/macrosTypes";
import { BaseButton, Icon } from "../../ui/index.ts";
import BaseCard from "../../ui/BaseCard.vue";

const store = useMacrosStore();
const { isBusy, mcodeFiles } = storeToRefs(store);

// Reads the mcode-only container directly. Each per-kind listing
// is independent in the store so ``storeToRefs(mcodeFiles)`` stays
// reactive without clobbering siblings on load.
const sorted = computed<MacroEntry[]>(() =>
  [...mcodeFiles.value].sort((a, b) => a.name.localeCompare(b.name)),
);

onMounted(async () => {
  await store.loadList(MACRO_KIND.MCODE);
});

async function onRefresh(): Promise<void> {
  await store.loadList(MACRO_KIND.MCODE);
}

async function onDelete(name: string): Promise<void> {
  await store.deleteMacro(MACRO_KIND.MCODE, name);
}
</script>

<template>
  <BaseCard title="⚙️ M-Codes">
    <template #header-actions>
      <span class="text-xs text-gray-400 font-mono">
        {{ sorted.length }} M-code{{ sorted.length === 1 ? '' : 's' }}
      </span>
      <BaseButton
        variant="secondary"
        size="sm"
        :disabled="isBusy"
        @click="onRefresh"
      >
        <template #icon><Icon name="refresh" class="h-3.5 w-3.5" /></template>
        Refresh
      </BaseButton>
    </template>

    <div v-if="sorted.length === 0" class="text-center text-gray-500 text-sm">
      <p>No M-codes yet.</p>
      <p class="mt-1 text-xs text-gray-600">
        Add one in <span class="font-mono">Machine Config</span> →
        <span class="font-mono">Macros</span> → <span class="font-mono">M-codes</span>.
      </p>
    </div>

    <ul v-else class="space-y-2">
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
          <BaseButton
            variant="primary"
            size="sm"
            @click="openInEditor({ source: 'm_codes', name: row.name })"
          >
            Edit
          </BaseButton>
          <BaseButton
            variant="danger"
            size="sm"
            :disabled="isBusy"
            @click="onDelete(row.name)"
          >
            Delete
          </BaseButton>
        </div>
      </li>
    </ul>
  </BaseCard>
</template>