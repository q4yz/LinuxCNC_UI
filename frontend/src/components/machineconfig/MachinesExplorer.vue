<script setup lang="ts">
// MachinesExplorer — browse the generated machine template sets under
// ``machine_config/machines/`` (``<machine>/configs/...``). Mirrors
// ProfilesExplorer one-for-one (folders at every depth, rename /
// move / delete, drag-drop upload, download) with two differences:
// files are templates and therefore editable, and there is no
// per-file action button — generation is started from the Profiles
// explorer.
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { useMachineConfigStore } from "../../stores/machineconfigStore";
import { ModalButtonStyle, useConfirm } from "../../core/confirm";
import type { DirectoryEntryModel } from "../../../generated/api/models/DirectoryEntryModel";
import { BaseButton, Icon } from "../../ui/index.ts";
import BaseInput from "../../ui/BaseInput.vue";

const emit = defineEmits(["edit"]);
const store = useMachineConfigStore();
const { machinesTree, isBusy } = storeToRefs(store);

const currentDirectory = ref("");
const activeMenu = ref("");
const createOpen = ref(false);
const newEntryKind = ref("file");
const newEntryName = ref("");
const isDragging = ref(false);
const entries = computed(() =>
  machinesTree.value.entries
    .filter((entry) => (entry.parent || "") === currentDirectory.value)
    .sort((a, b) => a.kind === b.kind ? a.name.localeCompare(b.name) : a.kind === "folder" ? -1 : 1),
);

const breadcrumbs = computed(() => currentDirectory.value.split("/").filter(Boolean));

function joinPath(directory: string, name: string) {
  return [directory, name].filter(Boolean).join("/");
}
function navigate(entry: DirectoryEntryModel) {
  activeMenu.value = "";
  if (entry.kind === "folder") currentDirectory.value = entry.path;
  else editFile(entry);
}
function goBack() {
  const parts = breadcrumbs.value.slice(0, -1);
  currentDirectory.value = parts.join("/");
}
function goToCrumb(index: number) {
  currentDirectory.value = breadcrumbs.value.slice(0, index + 1).join("/");
}
async function editFile(entry: DirectoryEntryModel) {
  if (entry.kind === "file") {
    const content = await store.readMachineContent(entry.path);
    if (content === null) return;
    emit("edit", entry.path, false, "machines", content);
  }
}
function formatSize(bytes: number) {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
async function onCreate() {
  const name = newEntryName.value.trim();
  if (!name) return;
  const path = joinPath(currentDirectory.value, name);
  if (newEntryKind.value === "folder") await store.createMachineFolder(path);
  else await store.createMachineFile(path);
  newEntryName.value = "";
  createOpen.value = false;
}
async function renameEntry(entry: DirectoryEntryModel) {
  activeMenu.value = "";
  const name = window.prompt("New name", entry.name)?.trim();
  if (name && name !== entry.name) await store.renameMachine(entry.path, joinPath(entry.parent || "", name));
}
async function copyOrMove(entry: DirectoryEntryModel) {
  activeMenu.value = "";
  const destination = window.prompt("Move to path", entry.path)?.trim();
  if (destination && destination !== entry.path) await store.renameMachine(entry.path, destination);
}
async function deleteEntry(entry: DirectoryEntryModel) {
  activeMenu.value = "";
  const shouldDelete = await useConfirm({
    title: "Delete entry",
    question: `Delete ${entry.path}? This cannot be undone.`,
    confirmButtonText: "Delete",
    confirmButtonStyle: ModalButtonStyle.DANGER,
    rejectButtonText: "Cancel",
  });
  if (shouldDelete) await store.deleteMachine(entry.path);
}
async function dropFiles(event: DragEvent) {
  isDragging.value = false;
  const files = Array.from(event.dataTransfer?.files || []);
  if (files.length) await store.uploadMachines(currentDirectory.value, files);
}
async function downloadMachineFile(entry: DirectoryEntryModel) {
  const content = await store.readMachineContent(entry.path);
  if (content === null) return;
  downloadBlob(new Blob([content], { type: "text/plain;charset=utf-8" }), entry.name);
}
function downloadBlob(content: string | Blob | object, name: string, mimeType = "text/plain;charset=utf-8") {
  const data = typeof content === "object" ? JSON.stringify(content, null, 2) : content;

  const blob = new Blob([data], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");

  anchor.href = url;
  anchor.download = name;
  anchor.style.display = "none";

  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);

  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 150);
}
</script>

<template>
  <div
    class="relative flex min-h-[360px] flex-col overflow-hidden rounded-lg border bg-gray-800 shadow-xl transition-colors"
    :class="isDragging ? 'border-blue-400 bg-blue-950/30' : 'border-gray-700'"
    @dragenter.prevent="isDragging = true"
    @dragover.prevent="isDragging = true"
    @dragleave.self="isDragging = false"
    @drop.prevent="dropFiles"
  >
    <div class="flex items-center justify-between border-b border-gray-600 bg-gray-700/50 px-4 py-3">
      <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-300">Machines</h2>
      <span class="font-mono text-xs text-gray-400">{{ entries.length }} items</span>
    </div>

    <nav class="flex min-h-11 items-center gap-2 border-b border-gray-700 px-3 py-2 text-sm">
      <BaseButton variant="ghost" size="sm" :disabled="!currentDirectory" @click="goBack" title="Back" aria-label="Back">
        <template #icon><Icon name="chevronLeft" class="h-4 w-4" /></template>
      </BaseButton>
      <button type="button" class="font-mono text-blue-300 hover:text-blue-200" @click="currentDirectory = ''">machines</button>
      <template v-for="(crumb, index) in breadcrumbs" :key="`${crumb}-${index}`">
        <span class="text-gray-600">/</span>
        <button type="button" class="truncate font-mono text-gray-300 hover:text-white" @click="goToCrumb(index)">{{ crumb }}</button>
      </template>
    </nav>

    <div v-if="isDragging" class="pointer-events-none absolute inset-2 z-20 flex items-center justify-center rounded border-2 border-dashed border-blue-400 bg-gray-950/80 font-semibold text-blue-200">
      Drop files into {{ currentDirectory || 'machines' }}
    </div>

    <ul v-if="entries.length" class="flex-1 space-y-1 overflow-y-auto p-2 pb-20">
      <li v-for="entry in entries" :key="entry.path" class="relative">
        <div
          class="flex cursor-pointer items-center gap-2 rounded border px-2 py-2 transition-colors"
          :class="entry.kind === 'folder' ? 'border-transparent hover:bg-gray-700/40' : 'border-transparent hover:bg-gray-700/40'"
          @click="navigate(entry)"
          @dblclick="editFile(entry)"
        >
          <span>{{ entry.kind === 'folder' ? '📁' : '📄' }}</span>
          <div class="min-w-0 flex-1">
            <div class="truncate font-mono text-sm text-gray-200" :title="entry.path">{{ entry.name }}</div>
            <div v-if="entry.kind === 'file'" class="text-[11px] text-gray-500">{{ formatSize(entry.size_bytes ?? 0) }}</div>
          </div>
          <BaseButton v-if="entry.kind === 'file'" variant="ghost" size="sm" title="Download" aria-label="Download" @click.stop="downloadMachineFile(entry)">↓</BaseButton>
          <BaseButton variant="ghost" size="sm" title="More actions" aria-label="More actions" @click.stop="activeMenu = activeMenu === entry.path ? '' : entry.path">⋮</BaseButton>
        </div>
        <div v-if="activeMenu === entry.path" class="absolute right-2 top-10 z-10 w-36 rounded border border-gray-600 bg-gray-900 py-1 text-sm shadow-xl">
          <button type="button" class="block w-full px-3 py-2 text-left hover:bg-gray-700" @click="renameEntry(entry)">Rename</button>
          <button type="button" class="block w-full px-3 py-2 text-left hover:bg-gray-700" @click="copyOrMove(entry)">Copy (Move)</button>
          <button type="button" class="block w-full px-3 py-2 text-left text-red-300 hover:bg-red-900/40" @click="deleteEntry(entry)">Delete</button>
        </div>
      </li>
    </ul>
    <div v-else class="flex-1 p-8 text-center text-sm text-gray-500">
      No machines yet. Generate one from a profile in the Profiles explorer.
    </div>

    <button type="button" class="sticky bottom-4 ml-auto mr-4 mb-4 h-12 w-12 rounded-full bg-blue-600 text-3xl text-white shadow-lg hover:bg-blue-500" title="Create file or folder" @click="createOpen = true">+</button>

    <div v-if="createOpen" class="absolute inset-0 z-30 flex items-center justify-center bg-black/70 p-4" @click.self="createOpen = false">
      <form class="w-full max-w-sm space-y-4 rounded-lg border border-gray-600 bg-gray-800 p-4 shadow-2xl" @submit.prevent="onCreate">
        <h3 class="font-semibold text-gray-100">Create in {{ currentDirectory || 'machines' }}</h3>
        <div class="flex gap-4 text-sm">
          <label><input v-model="newEntryKind" type="radio" value="file" /> File</label>
          <label><input v-model="newEntryKind" type="radio" value="folder" /> Folder</label>
        </div>
        <BaseInput v-model="newEntryName" autofocus type="text" placeholder="Name" class="w-full font-mono" />
        <div class="flex justify-end gap-2">
          <BaseButton variant="secondary" @click="createOpen = false">Cancel</BaseButton>
          <BaseButton variant="primary" type="submit" :disabled="isBusy || !newEntryName.trim()">Create</BaseButton>
        </div>
      </form>
    </div>
  </div>
</template>
