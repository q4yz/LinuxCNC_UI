<script setup lang="ts">
// MachinesExplorer — browse the generated machine template sets under
// ``machine_config/machines/`` (``<machine>/configs/...``). Mirrors
// ProfilesExplorer (folders at every depth, drag-drop upload, every
// row action in the "⋮" menu: edit, download, copy, move, delete).
// Differences: files are templates and therefore editable, generation
// is started from the Profiles explorer, ``.hal`` files can open the
// Visual HAL Editor scoped to that file, and root-level folders (the
// machines) can be started / set as the default machine.
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useMachineConfigStore } from "../../stores/machineconfigStore";
import { useDirectoryQuery } from "../../composables/useDirectoryQuery";
import { useConsoleStore } from "../../stores/console";
import type { FileEntry } from "../../entities/files";
import { formatFileDate, formatFileSize } from "../../helpers/fileFormat";
import { MachineLifecycleFacade } from "../../facades/machineLifecycleFacade";
import { openInEditor, EDITOR_SOURCES } from "../../helpers/openInEditor";
import { ActionMenu, BaseButton, FileDropZone, Icon } from "../../ui/index.ts";
import type { ActionMenuItem } from "../../ui/ActionMenu.vue";
import { confirmDelete, downloadText, suggestCopyPath } from "./explorerActions";
import BaseInput from "../../ui/BaseInput.vue";

const router = useRouter();

function isHalFile(entry: FileEntry): boolean {
  return entry.kind === "file" && entry.name.toLowerCase().endsWith(".hal");
}

function openHalEditor(entry: FileEntry): void {
  router.push({ name: "hal-editor", query: { file: entry.path } });
}

const emit = defineEmits(["edit"]);
const store = useMachineConfigStore();
const consoleStore = useConsoleStore();
const { machinesTree, isBusy } = storeToRefs(store);

// ─────────────────────────────────────────────────────────────────
// Machine lifecycle (system service, :8001)
//
// Root-level folders under ``machines/`` ARE the machines. Each one
// gets "Start" (persist as default + launch its
// config/machine.ini) and "Set main" (persist as default only) —
// see ``backend/system/routers/machine_lifecycle.py``.
// ─────────────────────────────────────────────────────────────────
const defaultMachine = ref<string | null>(null);
const startingPath = ref<string | null>(null);
const settingMainPath = ref<string | null>(null);

/** Root-level folders are machine folders. */
function isMachineFolder(entry: FileEntry): boolean {
  return entry.kind === "folder" && !entry.parent;
}

async function refreshLifecycleStatus(): Promise<void> {
  try {
    const status = await MachineLifecycleFacade.getStatus();
    defaultMachine.value = status.default_machine;
  } catch {
    // The explorer stays fully usable without lifecycle info —
    // the buttons surface errors when pressed.
  }
}

function lifecycleError(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

async function startMachine(entry: FileEntry): Promise<void> {
  if (startingPath.value !== null) return;
  // The backend refuses (409) while any LinuxCNC session runs — its
  // reason (e.g. started from another process) is shown below.
  startingPath.value = entry.path;
  try {
    const status = await MachineLifecycleFacade.startMachine(entry.name);
    defaultMachine.value = status.default_machine;
    consoleStore.success(
      `Machine ${entry.name} started (pid ${status.started_pid ?? "?"})`,
    );
  } catch (err: unknown) {
    const status = (err as { status?: unknown } | null)?.status;
    if (status === 409) {
      consoleStore.warning(`Cannot start ${entry.name}: ${lifecycleError(err)}`, { popup: true, lifetime: null });
    } else if (status === 404) {
      consoleStore.error(
        `Cannot start ${entry.name}: no machines/${entry.name}/config/machine.ini`,
      );
    } else {
      // Most likely a crash-on-launch (bad INI, realtime error, ...)
      // — open the console log so the operator sees why without
      // shell access.
      consoleStore.error(`Failed to start ${entry.name}: ${lifecycleError(err)}`);
      void openInEditor({
        source: EDITOR_SOURCES.MACHINE_LOG,
        name: "linuxcnc_console.log",
        readOnly: true,
      });
    }
  } finally {
    startingPath.value = null;
  }
}

async function selectAsMain(entry: FileEntry): Promise<void> {
  if (settingMainPath.value !== null) return;

  settingMainPath.value = entry.path;
  try {
    const status = await MachineLifecycleFacade.setDefaultMachine(entry.name);
    defaultMachine.value = status.default_machine;
    consoleStore.success(`${entry.name} is now the default machine`);
  } catch (err: unknown) {
    const status = (err as { status?: unknown } | null)?.status;
    if (status === 404) {
      consoleStore.error(
        `Cannot select ${entry.name}: no machines/${entry.name}/config/machine.ini`,
      );
    } else {
      consoleStore.error(`Failed to set default: ${lifecycleError(err)}`);
    }
  } finally {
    settingMainPath.value = null;
  }
}

onMounted(() => {
  void refreshLifecycleStatus();
});

// Lives in the URL so opening a file and coming back keeps the folder.
const currentDirectory = useDirectoryQuery("machinesDir");
const createOpen = ref(false);
const newEntryKind = ref("file");
const newEntryName = ref("");
const entries = computed(() =>
  machinesTree.value.entries
    .filter((entry) => (entry.parent || "") === currentDirectory.value)
    .sort((a, b) => a.kind === b.kind ? a.name.localeCompare(b.name) : a.kind === "folder" ? -1 : 1),
);

const breadcrumbs = computed(() => currentDirectory.value.split("/").filter(Boolean));

function joinPath(directory: string, name: string) {
  return [directory, name].filter(Boolean).join("/");
}
function navigate(entry: FileEntry) {
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
async function editFile(entry: FileEntry) {
  if (entry.kind === "file") {
    const content = await store.readMachineContent(entry.path);
    if (content === null) return;
    emit("edit", entry.path, false, "machines", content);
  }
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
// --- "⋮" menu ---------------------------------------------------------- //

const COMMON_ITEMS: ActionMenuItem[] = [
  { key: "copy", label: "Copy…", separated: true },
  { key: "move", label: "Move / rename…" },
  { key: "delete", label: "Delete", danger: true, separated: true },
];

function menuItems(entry: FileEntry): ActionMenuItem[] {
  if (entry.isFolder) {
    const lifecycle: ActionMenuItem[] = isMachineFolder(entry)
      ? [
          { key: "start", label: "Start machine", disabled: startingPath.value !== null },
        ]
      : [];
    return [{ key: "open", label: "Open" }, ...lifecycle, ...COMMON_ITEMS];
  }
  return [
    { key: "edit", label: "Edit" },
    ...(isHalFile(entry) ? [{ key: "hal", label: "Open in Visual HAL Editor" }] : []),
    { key: "download", label: "Download" },
    ...COMMON_ITEMS,
  ];
}

async function onMenu(entry: FileEntry, key: string): Promise<void> {
  if (key === "open") navigate(entry);
  else if (key === "edit") await editFile(entry);
  else if (key === "hal") openHalEditor(entry);
  else if (key === "start") await startMachine(entry);
  else if (key === "download") await downloadMachineFile(entry);
  else if (key === "copy") await copyEntry(entry);
  else if (key === "move") await moveEntry(entry);
  else if (key === "delete") await deleteEntry(entry);
}

async function copyEntry(entry: FileEntry) {
  const taken = new Set(machinesTree.value.entries.map((e) => e.path));
  const destination = window.prompt(`Copy ${entry.path} to`, suggestCopyPath(entry.path, taken))?.trim();
  if (destination && destination !== entry.path) await store.copyMachine(entry.path, destination);
}
async function moveEntry(entry: FileEntry) {
  const destination = window.prompt(`Move / rename ${entry.path} to`, entry.path)?.trim();
  if (destination && destination !== entry.path) await store.renameMachine(entry.path, destination);
}
async function deleteEntry(entry: FileEntry) {
  const isDefault = isMachineFolder(entry) && defaultMachine.value === entry.name;
  const { confirmed, recursive } = await confirmDelete(
    entry,
    machinesTree.value.entries,
    isDefault ? `${entry.name} is the default ("main") machine — Start machine will have nothing to start.` : "",
  );
  if (!confirmed) return;
  await store.deleteMachine(entry.path, recursive);
  if (isDefault) void refreshLifecycleStatus();
}
async function uploadFiles(files: File[]) {
  await store.uploadMachines(currentDirectory.value, files);
}
async function downloadMachineFile(entry: FileEntry) {
  const content = await store.readMachineContent(entry.path);
  if (content !== null) downloadText(entry.name, content);
}
</script>

<template>
  <FileDropZone
    v-slot="{ openPicker }"
    :target="currentDirectory || 'machines'"
    :disabled="isBusy"
    class="flex min-h-[360px] flex-col overflow-hidden rounded-lg border border-gray-700 bg-gray-800"
    @files="uploadFiles"
  >
    <div class="flex items-center justify-between border-b border-gray-600 bg-gray-700/50 px-4 py-3">
      <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-300">Machines</h2>
      <div class="flex items-center gap-3">
        <span class="font-mono text-xs text-gray-400">{{ entries.length }} items</span>
        <BaseButton variant="primary" size="sm" :disabled="isBusy" data-test="machines-upload" @click="openPicker">
          <span class="mr-1">⬆</span> Upload
        </BaseButton>
      </div>
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
            <div class="text-[11px] text-gray-500" data-test="file-entry-meta">
              <template v-if="entry.isFile">{{ formatFileSize(entry.sizeBytes) }} · </template>{{ formatFileDate(entry.modified) }}
            </div>
          </div>
          <!-- Root-level machine folders: the default ("main") badge or the
               "Set as default" button next to ⋮; Start lives in the menu. -->
          <template v-if="isMachineFolder(entry)">
            <span
              v-if="startingPath === entry.path"
              class="rounded border border-blue-600 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-blue-300"
            >starting…</span>
            <span
              v-if="defaultMachine === entry.name"
              class="rounded border border-amber-600 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-amber-300"
              title="Default machine — started by generic Start-machine buttons"
            >
              main
            </span>
            <BaseButton
              v-else
              variant="secondary"
              size="sm"
              :loading="settingMainPath === entry.path"
              :disabled="settingMainPath !== null"
              title="Make this the default machine (started by the generic Start-machine buttons)"
              :data-test="`machines-set-default-${entry.path}`"
              @click.stop="selectAsMain(entry)"
              @dblclick.stop
            >Set as default</BaseButton>
          </template>
          <span @click.stop @dblclick.stop>
            <ActionMenu :items="menuItems(entry)" :test-id="`machines-entry-${entry.path}`" @select="onMenu(entry, $event)" />
          </span>
        </div>
      </li>
    </ul>
    <div v-else class="flex-1 p-8 text-center text-sm text-gray-500">
      No machines yet. Generate one from a profile in the Profiles explorer, or drop files here.
    </div>

    <button type="button" class="sticky bottom-4 ml-auto mr-4 mb-4 h-12 w-12 rounded-full bg-blue-600 text-3xl text-white hover:bg-blue-500" title="Create file or folder" @click="createOpen = true">+</button>

    <div v-if="createOpen" class="absolute inset-0 z-30 flex items-center justify-center bg-black/70 p-4" @click.self="createOpen = false">
      <form class="w-full max-w-sm space-y-4 rounded-lg border border-gray-600 bg-gray-800 p-4" @submit.prevent="onCreate">
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
  </FileDropZone>
</template>
