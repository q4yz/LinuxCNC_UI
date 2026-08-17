<script setup>
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { useMachineConfigStore } from "../store";
import { ModalButtonStyle, useConfirm } from "../../../core/confirm";

const emit = defineEmits(["edit"]);
const store = useMachineConfigStore();
const { profilesTree, selectedProfilePath, isBusy } = storeToRefs(store);

const currentDirectory = ref("");
const activeMenu = ref("");
const createOpen = ref(false);
const newEntryKind = ref("file");
const newEntryName = ref("");
const isDragging = ref(false);
const entries = computed(() =>
  profilesTree.value.entries
    .filter((entry) => (entry.parent || "") === currentDirectory.value)
    .sort((a, b) => a.kind === b.kind ? a.name.localeCompare(b.name) : a.kind === "folder" ? -1 : 1),
);

const breadcrumbs = computed(() => currentDirectory.value.split("/").filter(Boolean));

function joinPath(directory, name) {
  return [directory, name].filter(Boolean).join("/");
}
function navigate(entry) {
  activeMenu.value = "";
  if (entry.kind === "folder") currentDirectory.value = entry.path;
  else store.selectProfile(entry.path);
}
function goBack() {
  const parts = breadcrumbs.value.slice(0, -1);
  currentDirectory.value = parts.join("/");
}
function goToCrumb(index) {
  currentDirectory.value = breadcrumbs.value.slice(0, index + 1).join("/");
}
async function editFile(entry) {
  if (entry.kind === "file") {
    store.selectProfile(entry.path);

    // Fetch the content first
    const content = await store.readProfileContent(entry.path);
    if (content === null) return; // Failsafe if the read failed

    // Emit: filename, readOnly (false), mode ('profile'), content
    emit("edit", entry.path, false, "profile", content);
  }
}
function formatSize(bytes) {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
async function onCompile(entry) {
  store.selectProfile(entry.path);
  await store.compile(entry.path);
}
async function onCreate() {
  const name = newEntryName.value.trim();
  if (!name) return;
  const path = joinPath(currentDirectory.value, name);
  if (newEntryKind.value === "folder") await store.createFolder(path);
  else await store.createFile(path);
  newEntryName.value = "";
  createOpen.value = false;
}
async function renameEntry(entry) {
  activeMenu.value = "";
  const name = window.prompt("New name", entry.name)?.trim();
  if (name && name !== entry.name) await store.renameProfile(entry.path, joinPath(entry.parent || "", name));
}
async function copyOrMove(entry) {
  activeMenu.value = "";
  const destination = window.prompt("Move to path", entry.path)?.trim();
  if (destination && destination !== entry.path) await store.renameProfile(entry.path, destination);
}
async function deleteEntry(entry) {
  activeMenu.value = "";
  const shouldDelete = await useConfirm({
    title: "Profil löschen",
    question: `Delete ${entry.path}? This cannot be undone.`,
    confirmButtonText: "Löschen",
    confirmButtonStyle: ModalButtonStyle.DANGER,
    rejectButtonText: "Abbrechen",
  });
  if (shouldDelete) await store.deleteProfile(entry.path);
}
async function dropFiles(event) {
  isDragging.value = false;
  const files = Array.from(event.dataTransfer?.files || []);
  if (files.length) await store.uploadProfiles(currentDirectory.value, files);
}
async function downloadProfile(entry) {
  const content = await store.readProfileContent(entry.path);
  if (content === null) return;
  downloadBlob(new Blob([content], { type: "text/plain;charset=utf-8" }), entry.name);
}
function downloadBlob(content, name, mimeType = "text/plain;charset=utf-8") {
  // Prevent the Axios [object Object] trap
  const data = typeof content === "object" ? JSON.stringify(content, null, 2) : content;

  const blob = new Blob([data], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");

  anchor.href = url;
  anchor.download = name;
  anchor.style.display = "none";
const rootChildren = computed(() => childrenOf(null));

  // Prevent the Firefox trap
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);

  // Prevent the Safari trap
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
      <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-300">Profiles</h2>
      <span class="font-mono text-xs text-gray-400">{{ entries.length }} items</span>
    </div>

    <nav class="flex min-h-11 items-center gap-2 border-b border-gray-700 px-3 py-2 text-sm">
      <button type="button" class="rounded px-2 py-1 text-gray-200 hover:bg-gray-700 disabled:text-gray-600" :disabled="!currentDirectory" @click="goBack" title="Back">←</button>
      <button type="button" class="font-mono text-blue-300 hover:text-blue-200" @click="currentDirectory = ''">profiles</button>
      <template v-for="(crumb, index) in breadcrumbs" :key="`${crumb}-${index}`">
        <span class="text-gray-600">/</span>
        <button type="button" class="truncate font-mono text-gray-300 hover:text-white" @click="goToCrumb(index)">{{ crumb }}</button>
      </template>
    </nav>

    <div v-if="isDragging" class="pointer-events-none absolute inset-2 z-20 flex items-center justify-center rounded border-2 border-dashed border-blue-400 bg-gray-950/80 font-semibold text-blue-200">
      Drop files into {{ currentDirectory || 'profiles' }}
    </div>

    <ul v-if="entries.length" class="flex-1 space-y-1 overflow-y-auto p-2 pb-20">
      <li v-for="entry in entries" :key="entry.path" class="relative">
        <div
          class="flex cursor-pointer items-center gap-2 rounded border px-2 py-2 transition-colors"
          :class="selectedProfilePath === entry.path ? 'border-blue-500 bg-blue-600/30' : 'border-transparent hover:bg-gray-700/40'"
          @click="navigate(entry)"
          @dblclick="editFile(entry)"
        >
          <span>{{ entry.kind === 'folder' ? '📁' : '📄' }}</span>
          <div class="min-w-0 flex-1">
            <div class="truncate font-mono text-sm text-gray-200" :title="entry.path">{{ entry.name }}</div>
            <div v-if="entry.kind === 'file'" class="text-[11px] text-gray-500">{{ formatSize(entry.size_bytes) }}</div>
          </div>
          <span v-if="entry.kind === 'file' && entry.has_marker" class="rounded bg-purple-700/40 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-purple-200">#Start</span>
          <button v-if="entry.kind === 'file' && entry.has_marker" type="button" class="rounded bg-purple-600 px-2 py-1 text-xs font-semibold text-white hover:bg-purple-500 disabled:bg-purple-900" :disabled="isBusy" @click.stop="onCompile(entry)">Compile</button>
          <button v-if="entry.kind === 'file'" type="button" class="rounded px-2 py-1 text-gray-300 hover:bg-gray-600" title="Download" @click.stop="downloadProfile(entry)">↓</button>
          <button type="button" class="rounded px-2 py-1 text-lg leading-none text-gray-300 hover:bg-gray-600" title="More actions" @click.stop="activeMenu = activeMenu === entry.path ? '' : entry.path">⋮</button>
        </div>
        <div v-if="activeMenu === entry.path" class="absolute right-2 top-10 z-10 w-36 rounded border border-gray-600 bg-gray-900 py-1 text-sm shadow-xl">
          <button type="button" class="block w-full px-3 py-2 text-left hover:bg-gray-700" @click="renameEntry(entry)">Rename</button>
          <button type="button" class="block w-full px-3 py-2 text-left hover:bg-gray-700" @click="copyOrMove(entry)">Copy (Move)</button>
          <button type="button" class="block w-full px-3 py-2 text-left text-red-300 hover:bg-red-900/40" @click="deleteEntry(entry)">Delete</button>
        </div>
      </li>
    </ul>
    <div v-else class="flex-1 p-8 text-center text-sm text-gray-500">This folder is empty. Drop files here or use + to create one.</div>

    <button type="button" class="sticky bottom-4 ml-auto mr-4 mb-4 h-12 w-12 rounded-full bg-blue-600 text-3xl text-white shadow-lg hover:bg-blue-500" title="Create file or folder" @click="createOpen = true">+</button>

    <div v-if="createOpen" class="absolute inset-0 z-30 flex items-center justify-center bg-black/70 p-4" @click.self="createOpen = false">
      <form class="w-full max-w-sm space-y-4 rounded-lg border border-gray-600 bg-gray-800 p-4 shadow-2xl" @submit.prevent="onCreate">
        <h3 class="font-semibold text-gray-100">Create in {{ currentDirectory || 'profiles' }}</h3>
        <div class="flex gap-4 text-sm">
          <label><input v-model="newEntryKind" type="radio" value="file" /> File</label>
          <label><input v-model="newEntryKind" type="radio" value="folder" /> Folder</label>
        </div>
        <input v-model="newEntryName" autofocus type="text" placeholder="Name" class="w-full rounded border border-gray-600 bg-gray-900 px-3 py-2 font-mono text-gray-200" />
        <div class="flex justify-end gap-2">
          <button type="button" class="rounded bg-gray-600 px-3 py-2 hover:bg-gray-500" @click="createOpen = false">Cancel</button>
          <button type="submit" class="rounded bg-blue-600 px-3 py-2 font-semibold hover:bg-blue-500 disabled:bg-blue-900" :disabled="isBusy || !newEntryName.trim()">Create</button>
        </div>
      </form>
    </div>
  </div>
</template>
