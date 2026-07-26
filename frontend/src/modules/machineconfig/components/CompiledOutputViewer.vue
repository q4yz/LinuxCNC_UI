<script setup>
// CompiledOutputViewer — read-only viewer for the artifacts that the
// compiler just staged into ``machine_config/ready_for_deploy``.
//
// Every file is rendered as a card; clicking the "View" button opens a
// modal containing the file text. The modal reuses the
// :class:`ConfigEditor` widget in read-only mode so the operator
// gets the same CodeMirror styling they have everywhere else.

import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { useMachineConfigStore } from "../store.js";
import ConfigEditor from "../../../components/ConfigEditor.vue";

const store = useMachineConfigStore();
const { stagedFiles, stagedContents, stagedTotalSize, isBusy } = storeToRefs(store);

const viewModalOpen = ref(false);
const viewModalTitle = ref("");
const viewModalContent = ref("");
const viewModalFilename = ref("");

const fileCards = computed(() =>
  stagedFiles.value.map((file) => ({
    name: file.name,
    size: file.size_bytes,
    description: descriptionFor(file.name),
    modalTitle: `Staged / ${file.name}`,
  })),
);

function descriptionFor(name) {
  switch (name) {
    case "machine.cfg":
      return "Source profile snapshot, ready to deploy.";
    case "linuxcnc.ini":
      return "Generated LinuxCNC INI configuration.";
    case "machine.hal":
      return "Generated HAL net list.";
    case "remora.json":
      return "Generated Remora board payload (flash before deploy if required).";
    default:
      return "Generated artifact.";
  }
}

function formatSize(bytes) {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

async function openModal(card) {
  const content =
    stagedContents.value[card.name] ?? (await store.readStagedFileContent(card.name));
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
        <span class="mr-2">🛡</span> Compiled Output
        <span class="ml-2 px-1.5 py-0.5 rounded bg-yellow-700/40 text-yellow-200 text-[10px] uppercase tracking-wider">
          Read-only
        </span>
      </h2>
      <span class="text-xs text-gray-400 font-mono">
        {{ stagedFiles.length }} file(s) · {{ formatSize(stagedTotalSize) }}
      </span>
    </div>

    <div v-if="stagedFiles.length === 0" class="p-6 text-center text-gray-500 text-sm">
      Nothing staged yet. Compile a profile to populate the staging area.
    </div>

    <ul v-else class="p-3 space-y-2">
      <li
        v-for="card in fileCards"
        :key="card.name"
        class="flex items-center justify-between gap-4 rounded-lg border border-gray-700 bg-gray-900/60 p-3"
      >
        <div class="min-w-0">
          <div class="font-mono text-sm font-semibold text-gray-100 truncate flex items-center gap-2">
            🔒 {{ card.name }}
            <span class="text-[10px] text-yellow-300/80 uppercase tracking-wider">locked</span>
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

    <div
      v-if="viewModalOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
    >
      <div class="flex h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-lg border border-gray-700 bg-gray-900 shadow-2xl">
        <div class="flex items-center justify-between border-b border-gray-700 bg-gray-800 px-4 py-3">
          <div>
            <div class="text-xs uppercase tracking-wider text-yellow-300 font-semibold">
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
        <div class="flex-1 min-h-0">
          <ConfigEditor
            v-model="viewModalContent"
            :read-only="true"
            :filename="viewModalFilename || viewModalTitle"
          />
        </div>
      </div>
    </div>
  </div>
</template>