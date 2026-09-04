<script setup lang="ts">
// ActivePanel — "Active" dashboard. Shows the currently running
// machine name (extracted from the active INI's [EMC] section) plus
// the list of files currently in ``machine_config/active``.
//
// Read-only, downloadable individually or as a ZIP. The active files are post-deploy
// snapshots — operators can download them as a failure-recovery
// record or to inspect what the controller is actually running.

import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useMachineConfigStore } from "../../stores/machineconfigStore";
import { openInEditor } from "../../helpers/openInEditor";
import { BaseButton, Icon } from "../../ui/index.ts";
import BaseCard from "../../ui/BaseCard.vue";

const store = useMachineConfigStore();
const { activeListing, activeContents, activeTotalSize, isBusy } = storeToRefs(store);

const fileCards = computed(() =>
  // In ``<script setup lang="ts">`` the ref returned by ``storeToRefs`` is NOT
  // auto-unwrapped in JS — only the template unwraps refs. So the
  // reactive array is on ``activeListing.value.files``, not
  // ``activeListing.files`` (which is ``undefined`` on the ref).
  // The previous version silently mapped an empty array, which
  // is why the user saw ``0 file(s) · 9.4 KB`` — the size came from
  // a separate computed in the store that read the underlying
  // reactive object directly.
  (activeListing.value.files || []).map((file) => ({
    name: file.name,
    size: file.size_bytes,
    description: descriptionFor(file.name),
    modalTitle: `Active / ${file.name}`,
  })),
);

interface FileCard {
  name: string;
  size: number;
  description: string;
  modalTitle: string;
}

interface ZipEntry {
  name: string;
  data: Uint8Array;
}

interface ZipCentralEntry {
  name: Uint8Array;
  crc: number;
  size: number;
  offset: number;
}

function descriptionFor(name: string) {
  switch (name) {
    case "machine.cfg":
      return "Source profile snapshot for the live configuration.";
    case "linuxcnc.ini":
      return "Active LinuxCNC INI configuration.";
    case "machine.hal":
      return "Active HAL net list.";
    case "hardware.json":
      return "Active hardware record (v2 model).";
    case "remora.json":
      return "Active Remora board payload.";
    default:
      return "Active file.";
  }
}

function formatSize(bytes: number) {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

async function refresh() {
  await store.loadActive();
}

// "View" used to mount ``Editor`` inline inside a modal. The
// universal editor contract (issue #132) routes through
// ``/editor?source=active&name=...&readOnly=true`` instead so the
// editor only lives in one place.
function openInEditorView(card: FileCard) {
  return openInEditor({
    source: 'active',
    name: card.name,
    readOnly: true,
  })
}

async function downloadFile(name: string) {
  const content = activeContents.value[name] ?? (await store.readActiveFileContent(name));
  if (content === null) return;
  saveBlob(new Blob([content], { type: "application/octet-stream" }), name);
}

async function downloadZip() {
  const encoder = new TextEncoder();
  const files: ZipEntry[] = [];
  for (const file of activeListing.value.files || []) {
    const content = activeContents.value[file.name] ?? (await store.readActiveFileContent(file.name));
    if (content === null) return;
    files.push({ name: file.name, data: encoder.encode(content) });
  }
  saveBlob(new Blob([createZip(files)], { type: "application/zip" }), "active-output.zip");
}

// --- ZIP helpers ---

function createZip(files: ZipEntry[]) {
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
function zipHeader(signature: number, crc: number, size: number, nameLength: number) {
  const bytes = new Uint8Array(30); const view = new DataView(bytes.buffer);
  view.setUint32(0, signature, true); view.setUint16(4, 20, true); view.setUint32(14, crc, true);
  view.setUint32(18, size, true); view.setUint32(22, size, true); view.setUint16(26, nameLength, true); return bytes;
}
function centralHeader(file: ZipCentralEntry) {
  const bytes = new Uint8Array(46); const view = new DataView(bytes.buffer);
  view.setUint32(0, 0x02014b50, true); view.setUint16(4, 20, true); view.setUint16(6, 20, true);
  view.setUint32(16, file.crc, true); view.setUint32(20, file.size, true); view.setUint32(24, file.size, true);
  view.setUint16(28, file.name.length, true); view.setUint32(42, file.offset, true); return bytes;
}
function endHeader(count: number, size: number, offset: number) {
  const bytes = new Uint8Array(22); const view = new DataView(bytes.buffer);
  view.setUint32(0, 0x06054b50, true); view.setUint16(8, count, true); view.setUint16(10, count, true);
  view.setUint32(12, size, true); view.setUint32(16, offset, true); return bytes;
}
function crc32(data: Uint8Array) {
  let crc = -1;
  for (const byte of data) { crc ^= byte; for (let i = 0; i < 8; i += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1)); }
  return (crc ^ -1) >>> 0;
}
function concatBytes(parts: Uint8Array[]) {
  const result = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let offset = 0; for (const part of parts) { result.set(part, offset); offset += part.length; } return result;
}
function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
  anchor.href = url; anchor.download = filename; anchor.click(); URL.revokeObjectURL(url);
}
</script>

<template>
  <BaseCard title="⚡ Active">
    <template #header-actions>
      <span class="px-1.5 py-0.5 rounded bg-yellow-700/40 text-yellow-200 text-[10px] uppercase tracking-wider">
        Read-only
      </span>
      <span class="text-xs text-gray-400 font-mono">
        {{ fileCards.length }} file(s) · {{ formatSize(activeTotalSize) }}
      </span>
      <BaseButton
        variant="primary"
        size="sm"
        :disabled="isBusy || !fileCards.length"
        @click="downloadZip"
      >
        Download ZIP
      </BaseButton>
      <BaseButton
        variant="secondary"
        size="sm"
        :disabled="isBusy"
        @click="refresh"
      >
        <template #icon><Icon name="refresh" class="h-3.5 w-3.5" /></template>
        Refresh
      </BaseButton>
    </template>




      <div class="mb-3 pb-3 border-b border-gray-700 p-4">
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

      <div v-if="fileCards.length === 0" class="text-center text-gray-500 text-sm">
        The active directory is empty. Stage and deploy a profile to populate it.
      </div>

      <ul v-else class="space-y-2">
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
            <BaseButton
              variant="secondary"
              size="sm"
              :disabled="isBusy"
              @click="downloadFile(card.name)"
            >
              Download
            </BaseButton>
            <BaseButton
              variant="primary"
              size="sm"
              :disabled="isBusy"
              @click="openInEditorView(card)"
            >
              View
            </BaseButton>
          </div>
        </li>
      </ul>

  </BaseCard>
</template>
