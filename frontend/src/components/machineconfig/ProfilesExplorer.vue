<script setup lang="ts">
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { useMachineConfigStore } from "../../stores/machineconfigStore";
import { useDirectoryQuery } from "../../composables/useDirectoryQuery";
import { ModalButtonStyle, useConfirm } from "../../core/confirm";
import type { FileEntry } from "../../entities/files";
import { formatFileDate, formatFileSize } from "../../helpers/fileFormat";
import { ActionMenu, BaseButton, FileDropZone, Icon } from "../../ui/index.ts";
import type { ActionMenuItem } from "../../ui/ActionMenu.vue";
import { confirmDelete, downloadText, suggestCopyPath } from "./explorerActions";
import BaseInput from "../../ui/BaseInput.vue";
import BaseCard from "../../ui/BaseCard.vue";

const emit = defineEmits(["edit"]);
const store = useMachineConfigStore();
const { profilesTree, selectedProfilePath, isBusy, generateProblems } = storeToRefs(store);

// Lives in the URL so opening a file and coming back keeps the folder.
const currentDirectory = useDirectoryQuery("profilesDir");
const createOpen = ref(false);
const newEntryKind = ref("file");
const newEntryName = ref("");
// Profile whose failed-generate problems are open (the "!" popup).
const problemsPath = ref<string | null>(null);

const entries = computed(() =>
  profilesTree.value.entries
    .filter((entry) => (entry.parent || "") === currentDirectory.value)
    .sort((a, b) => a.kind === b.kind ? a.name.localeCompare(b.name) : a.kind === "folder" ? -1 : 1),
);


const breadcrumbs = computed(() => currentDirectory.value.split("/").filter(Boolean));

function joinPath(directory: string, name: string) {
  return [directory, name].filter(Boolean).join("/");
}
function navigate(entry: FileEntry) {
  if (entry.kind === "folder") currentDirectory.value = entry.path;
  else store.selectProfile(entry.path);
}
function goBack() {
  const parts = breadcrumbs.value.slice(0, -1);
  currentDirectory.value = parts.join("/");
}
function goToCrumb(index: number) {
  currentDirectory.value = breadcrumbs.value.slice(0, index + 1).join("/");
}
async function editFile(entry: FileEntry) {
  if (entry.kind === "file") {
    store.selectProfile(entry.path);

    // Fetch the content first
    const content = await store.readProfileContent(entry.path);
    if (content === null) return; // Failsafe if the read failed

    // Emit: filename, readOnly (false), mode ('profile'), content
    emit("edit", entry.path, false, "profile", content);
  }
}
async function onGenerate(entry: FileEntry) {
  store.selectProfile(entry.path);
  const outcome = await store.generateMachine(entry.path);
  if (outcome.status === "conflict") {
    const override = await useConfirm({
      title: "Machine exists",
      question: `Machine "${outcome.machine}" already exists (${outcome.existing.length} files). Override its configuration?`,
      confirmButtonText: "Override",
      confirmButtonStyle: ModalButtonStyle.DANGER,
      rejectButtonText: "Cancel",
    });
    if (override) await store.generateMachine(entry.path, { confirmOverride: true });
  }
}
function problemsOf(entry: FileEntry): string[] {
  return generateProblems.value[entry.path] ?? [];
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
// --- "⋮" menu ---------------------------------------------------------- //

function isProfileCfg(entry: FileEntry): boolean {
  return entry.isFile && entry.name.toLowerCase().endsWith(".cfg");
}

function menuItems(entry: FileEntry): ActionMenuItem[] {
  if (entry.isFolder) {
    return [
      { key: "open", label: "Open" },
      { key: "copy", label: "Copy…", separated: true },
      { key: "move", label: "Move / rename…" },
      { key: "delete", label: "Delete", danger: true, separated: true },
    ];
  }
  return [
    { key: "edit", label: "Edit" },
    { key: "download", label: "Download" },
    { key: "copy", label: "Copy…", separated: true },
    { key: "move", label: "Move / rename…" },
    { key: "delete", label: "Delete", danger: true, separated: true },
  ];
}

async function onMenu(entry: FileEntry, key: string): Promise<void> {
  if (key === "open") navigate(entry);
  else if (key === "edit") await editFile(entry);
  else if (key === "download") await downloadProfile(entry);
  else if (key === "copy") await copyEntry(entry);
  else if (key === "move") await moveEntry(entry);
  else if (key === "delete") await deleteEntry(entry);
}

async function copyEntry(entry: FileEntry) {
  const taken = new Set(profilesTree.value.entries.map((e) => e.path));
  const destination = window.prompt(`Copy ${entry.path} to`, suggestCopyPath(entry.path, taken))?.trim();
  if (destination && destination !== entry.path) await store.copyProfile(entry.path, destination);
}
async function moveEntry(entry: FileEntry) {
  const destination = window.prompt(`Move / rename ${entry.path} to`, entry.path)?.trim();
  if (destination && destination !== entry.path) await store.renameProfile(entry.path, destination);
}
async function deleteEntry(entry: FileEntry) {
  const { confirmed, recursive } = await confirmDelete(entry, profilesTree.value.entries);
  if (confirmed) await store.deleteProfile(entry.path, recursive);
}
async function uploadFiles(files: File[]) {
  await store.uploadProfiles(currentDirectory.value, files);
}
async function downloadProfile(entry: FileEntry) {
  const content = await store.readProfileContent(entry.path);
  if (content !== null) downloadText(entry.name, content);
}
</script>

<template>
  <FileDropZone
    v-slot="{ openPicker }"
    :target="currentDirectory || 'profiles'"
    :disabled="isBusy"
    class="flex min-h-[360px] flex-col"
    @files="uploadFiles"
  >
  <BaseCard class="relative flex flex-1 flex-col">
    <div class="flex items-center justify-between border-b border-gray-600 bg-gray-700/50 px-4 py-3">
      <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-300">Profiles</h2>
      <div class="flex items-center gap-3">
        <span class="font-mono text-xs text-gray-400">{{ entries.length }} items</span>
        <BaseButton variant="primary" size="sm" :disabled="isBusy" data-test="profiles-upload" @click="openPicker">
          <Icon name="upload" class="mr-1" /> Upload
        </BaseButton>
      </div>
    </div>

    <nav class="flex min-h-11 items-center gap-2 border-b border-gray-700 px-3 py-2 text-sm">
      <BaseButton variant="ghost" size="sm" :disabled="!currentDirectory" @click="goBack" title="Back" aria-label="Back">
        <template #icon><Icon name="chevronLeft" class="h-4 w-4" /></template>
      </BaseButton>
      <button type="button" class="font-mono text-blue-300 hover:text-blue-200" @click="currentDirectory = ''">profiles</button>
      <template v-for="(crumb, index) in breadcrumbs" :key="`${crumb}-${index}`">
        <span class="text-gray-600">/</span>
        <button type="button" class="truncate font-mono text-gray-300 hover:text-white" @click="goToCrumb(index)">{{ crumb }}</button>
      </template>
    </nav>

    <ul v-if="entries.length" class="flex-1 space-y-1 overflow-y-auto p-2 pb-20">
      <li v-for="entry in entries" :key="entry.path" class="relative">
        <div
          class="flex cursor-pointer items-center gap-2 rounded border px-2 py-2 transition-colors"
          :class="selectedProfilePath === entry.path ? 'border-blue-500 bg-blue-600/30' : 'border-transparent hover:bg-gray-700/40'"
          @click="navigate(entry)"
          @dblclick="editFile(entry)"
        >
          <Icon :name="entry.kind === 'folder' ? 'folder' : 'file'" class="text-gray-400" />
          <div class="min-w-0 flex-1">
            <div class="truncate font-mono text-sm text-gray-200" :title="entry.path">{{ entry.name }}</div>
            <div class="text-[11px] text-gray-500" data-test="file-entry-meta">
              <template v-if="entry.isFile">{{ formatFileSize(entry.sizeBytes) }} · </template>{{ formatFileDate(entry.modified) }}
            </div>
          </div>
          <span v-if="entry.kind === 'file' && entry.hasMarker" class="rounded bg-purple-700/40 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-purple-200">#Start</span>
          <!-- The one frequent action stays visible; everything else is in ⋮. -->
          <BaseButton
            v-if="isProfileCfg(entry)"
            variant="success"
            size="sm"
            :disabled="isBusy"
            :data-test="`profiles-generate-${entry.path}`"
            @click.stop="onGenerate(entry)"
            @dblclick.stop
          >Generate</BaseButton>
          <!-- The last generate failed: "!" opens every reason. -->
          <button
            v-if="problemsOf(entry).length"
            type="button"
            class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-red-600 text-sm font-bold text-white hover:bg-red-500"
            :title="`Generate failed (${problemsOf(entry).length} problem${problemsOf(entry).length === 1 ? '' : 's'}) — show details`"
            :aria-label="`Show why generating ${entry.name} failed`"
            :data-test="`profiles-generate-problems-${entry.path}`"
            @click.stop="problemsPath = entry.path"
            @dblclick.stop
          >!</button>
          <span @click.stop @dblclick.stop>
            <ActionMenu :items="menuItems(entry)" :test-id="`profiles-entry-${entry.path}`" @select="onMenu(entry, $event)" />
          </span>
        </div>
      </li>
    </ul>
    <div v-else class="flex-1 p-8 text-center text-sm text-gray-500">This folder is empty. Drop files here or use + to create one.</div>

    <button type="button" class=" block sticky bottom-4 ml-auto mr-4 mb-4 h-12 w-12 rounded-full bg-blue-600 text-3xl text-white hover:bg-blue-500" title="Create file or folder" @click="createOpen = true">+</button>

    <Teleport to="body">
    <div
      v-if="problemsPath && generateProblems[problemsPath]"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      data-test="profiles-generate-problems-dialog"
      @click.self="problemsPath = null"
    >
      <div class="flex max-h-[85vh] w-full max-w-2xl flex-col space-y-3 rounded-lg border border-red-700 bg-gray-800 p-4">
        <h3 class="font-semibold text-red-300">
          {{ problemsPath }} does not generate a runnable machine
        </h3>
        <p class="text-xs text-gray-400">Nothing was written. Fix these in the profile and generate again.</p>
        <ul class="flex-1 space-y-1 overflow-y-auto font-mono text-xs text-gray-200">
          <li
            v-for="(problem, index) in generateProblems[problemsPath]"
            :key="index"
            class="rounded border border-gray-700 bg-gray-900/60 px-2 py-1 whitespace-pre-wrap break-words"
          >{{ problem }}</li>
        </ul>
        <div class="flex justify-end">
          <BaseButton variant="secondary" @click="problemsPath = null">Close</BaseButton>
        </div>
      </div>
    </div>
    </Teleport>

    <div v-if="createOpen" class="absolute inset-0 z-30 flex items-center justify-center bg-black/70 p-4" @click.self="createOpen = false">
      <form class="w-full max-w-sm space-y-4 rounded-lg border border-gray-600 bg-gray-800 p-4" @submit.prevent="onCreate">
        <h3 class="font-semibold text-gray-100">Create in {{ currentDirectory || 'profiles' }}</h3>
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
  </BaseCard>
  </FileDropZone>
</template>
