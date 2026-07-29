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
import Editor from "../../../components/Editor.vue";

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

async function downloadFile(name) {
  const content = stagedContents.value[name] ?? (await store.readStagedFileContent(name));
  if (content === null) return;
  saveBlob(new Blob([content], { type: "application/octet-stream" }), name);
}

async function downloadZip() {
  const encoder = new TextEncoder();
  const files = [];
  for (const file of stagedFiles.value) {
    const content = stagedContents.value[file.name] ?? (await store.readStagedFileContent(file.name));
    if (content === null) return;
    files.push({ name: file.name, data: encoder.encode(content) });
  }
  saveBlob(new Blob([createZip(files)], { type: "application/zip" }), "compiled-output.zip");
}

function createZip(files) {
  const chunks = [];
  const central = [];
  let offset = 0;
  for (const file of files) {
    const name = new TextEncoder().encode(file.name);
    const crc = crc32(file.data);
    const local = zipHeader(0x04034b50, crc, file.data.length, name.length);
    chunks.push(local, name, file.data);
    central.push({ name, crc, size: file.data.length, offset });
    offset += local.length + name.length + file.data.length;
  }
  const centralOffset = offset;
  for (const file of central) {
    const header = centralHeader(file);
    chunks.push(header, file.name);
    offset += header.length + file.name.length;
  }
  chunks.push(endHeader(files.length, offset - centralOffset, centralOffset));
  return concatBytes(chunks);
}
function zipHeader(signature, crc, size, nameLength) {
  const bytes = new Uint8Array(30); const view = new DataView(bytes.buffer);
  view.setUint32(0, signature, true); view.setUint16(4, 20, true); view.setUint32(14, crc, true);
  view.setUint32(18, size, true); view.setUint32(22, size, true); view.setUint16(26, nameLength, true); return bytes;
}
function centralHeader(file) {
  const bytes = new Uint8Array(46); const view = new DataView(bytes.buffer);
  view.setUint32(0, 0x02014b50, true); view.setUint16(4, 20, true); view.setUint16(6, 20, true);
  view.setUint32(16, file.crc, true); view.setUint32(20, file.size, true); view.setUint32(24, file.size, true);
  view.setUint16(28, file.name.length, true); view.setUint32(42, file.offset, true); return bytes;
}
function endHeader(count, size, offset) {
  const bytes = new Uint8Array(22); const view = new DataView(bytes.buffer);
  view.setUint32(0, 0x06054b50, true); view.setUint16(8, count, true); view.setUint16(10, count, true);
  view.setUint32(12, size, true); view.setUint32(16, offset, true); return bytes;
}
function crc32(data) {
  let crc = -1;
  for (const byte of data) { crc ^= byte; for (let i = 0; i < 8; i += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1)); }
  return (crc ^ -1) >>> 0;
}
function concatBytes(parts) {
  const result = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let offset = 0; for (const part of parts) { result.set(part, offset); offset += part.length; } return result;
}
function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
  anchor.href = url; anchor.download = filename; anchor.click(); URL.revokeObjectURL(url);
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
      <div class="flex items-center gap-3">
        <span class="text-xs text-gray-400 font-mono">
          {{ stagedFiles.length }} file(s) · {{ formatSize(stagedTotalSize) }}
        </span>
        <button type="button" class="rounded bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-500 disabled:bg-blue-900" :disabled="isBusy || !stagedFiles.length" @click="downloadZip">
          Download ZIP
        </button>
      </div>
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
            class="rounded bg-gray-600 hover:bg-gray-500 disabled:bg-gray-800 px-3 py-1.5 text-sm font-semibold text-white"
            :disabled="isBusy"
            @click="downloadFile(card.name)"
          >
            Download
          </button>
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
        <!-- ``min-h-0`` defeats the flex default ``min-height: auto``
             so the editor can scroll inside the fixed-height modal. -->
        <div class="min-h-0 flex-1 overflow-hidden">
          <Editor
            v-model="viewModalContent"
            :read-only="true"
            :filename="viewModalFilename || viewModalTitle"
            mode="profile"
          />
        </div>
      </div>
    </div>
  </div>
</template>