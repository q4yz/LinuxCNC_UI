<script setup>
// ActivePanel — "Active" dashboard. Shows the currently running
// machine name (extracted from the active INI's [EMC] section) plus
// the list of files currently in ``machine_config/active``. Clicking
// a file opens a read-only modal so the operator can sanity-check
// what the controller is actually running.

import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { useMachineConfigStore } from "../store.js";
import Editor from "../../../components/Editor.vue";

const store = useMachineConfigStore();
const { activeListing, activeContents, activeTotalSize, isBusy } = storeToRefs(store);

const viewModalOpen = ref(false);
const viewModalTitle = ref("");
const viewModalContent = ref("");
const viewModalFilename = ref("");

const fileCards = computed(() =>
  (activeListing.files || []).map((file) => ({
    name: file.name,
    size: file.size_bytes,
    description: descriptionFor(file.name),
    modalTitle: `Active / ${file.name}`,
  })),
);

function descriptionFor(name) {
  switch (name) {
    case "machine.cfg":
      return "Source profile snapshot for the live configuration.";
    case "linuxcnc.ini":
      return "Active LinuxCNC INI configuration.";
    case "machine.hal":
      return "Active HAL net list.";
    case "remora.json":
      return "Active Remora board payload.";
    default:
      return "Active file.";
  }
}

function formatSize(bytes) {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

async function refresh() {
  await store.loadActive();
}

async function openModal(card) {
  const content =
    activeContents.value[card.name] ?? (await store.readActiveFileContent(card.name));
  viewModalTitle.value = card.modalTitle;
  viewModalContent.value = content || "";
  viewModalFilename.value = card.name;
  viewModalOpen.value = true;
}

function closeModal() {
  viewModalOpen.value = false;
  viewModalContent.value = "";
  viewModalFilename.value = "";
  viewModalTitle.value = "";
}
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden">
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex justify-between items-center">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        <span class="mr-2">⚡</span> Active
      </h2>
      <button
        type="button"
        class="px-2 py-1 text-xs rounded bg-gray-600 hover:bg-gray-500 text-white"
        :disabled="isBusy"
        @click="refresh"
      >
        ↻ Refresh
      </button>
    </div>

    <div class="p-4 border-b border-gray-700">
      <div class="text-xs uppercase tracking-wider text-gray-400 mb-1">
        Currently running machine
      </div>
      <div
        class="font-mono text-lg font-semibold"
        :class="activeListing.machine_name ? 'text-blue-300' : 'text-gray-500'"
      >
        {{ activeListing.machine_name || '(no active configuration)' }}
      </div>
    </div>

    <div v-if="fileCards.length === 0" class="p-6 text-center text-gray-500 text-sm">
      The active directory is empty. Stage and deploy a profile to populate it.
    </div>

    <ul v-else class="p-3 space-y-2">
      <li
        v-for="card in fileCards"
        :key="card.name"
        class="flex items-center justify-between gap-4 rounded-lg border border-gray-700 bg-gray-900/60 p-3"
      >
        <div class="min-w-0">
          <div class="font-mono text-sm font-semibold text-gray-100 truncate">
            {{ card.name }}
          </div>
          <div class="text-xs text-gray-400 truncate">{{ card.description }}</div>
        </div>
        <div class="flex items-center gap-3 shrink-0">
          <span class="text-xs text-gray-500 font-mono">{{ formatSize(card.size) }}</span>
          <button
            type="button"
            class="rounded bg-blue-600 hover:bg-blue-500 disabled:bg-blue-900 px-3 py-1.5 text-sm font-semibold text-white"
            :disabled="isBusy"
            @click="openModal(card)"
          >
            View
          </button>
        </div>
      </li>
    </ul>

    <div class="px-4 py-2 border-t border-gray-700 text-xs text-gray-400 font-mono">
      {{ fileCards.length }} file(s) · {{ formatSize(activeTotalSize) }}
    </div>

    <div
      v-if="viewModalOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
    >
      <div class="flex h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-lg border border-gray-700 bg-gray-900 shadow-2xl">
        <div class="flex items-center justify-between border-b border-gray-700 bg-gray-800 px-4 py-3">
          <div>
            <div class="text-xs uppercase tracking-wider text-blue-300 font-semibold">
              {{ viewModalTitle }}
            </div>
          </div>
          <button
            type="button"
            class="rounded bg-gray-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-gray-500"
            @click="closeModal"
          >
            Close
          </button>
        </div>
        <!-- ``min-h-0`` defeats the flex default ``min-height: auto``
             so the editor can scroll inside the fixed-height modal. -->
        <div class="min-h-0 flex-1 overflow-hidden">
          <Editor
            v-model="viewModalContent"
            :read-only="true"
            :filename="viewModalFilename || viewModalTitle"
            mode="config"
          />
        </div>
      </div>
    </div>
  </div>
</template>