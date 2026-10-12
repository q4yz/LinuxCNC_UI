<script setup lang="ts">
// File manager — G-code programs under nc_files/, with project folders.
// File calls go through ``filesFacade``, Load through ``progressFacade``;
// rows are the shared ``FileEntry`` entity, addressed by their path
// relative to nc_files/ (``project/part.ngc``). The open folder lives in
// the URL (``?programsDir=``) so returning from the editor keeps it.
// Upload / drop go into the open folder (shared ``FileDropZone``); the
// blue ⊕ in the corner creates a folder. Routes the user to
// ``EditorView`` on Edit so the page chrome stays visible while editing.

import {ref, shallowRef, computed, onMounted, watch} from 'vue'

import {useConsoleStore} from '../stores/console'
import {openInEditor} from '../helpers/openInEditor'
import {describeErrorOr, errorStatus} from '../core/error-format'
import {filesFacade} from '../facades/filesFacade'
import {progressFacade} from '../facades/progressFacade'
import type {FileEntry} from '../entities/files'
import {formatFileDate as formatDate, formatFileSize as formatSize} from '../helpers/fileFormat'
import {ActionMenu, BaseButton, FileDropZone} from '../ui/index.ts'
import type {ActionMenuItem} from '../ui/ActionMenu.vue'
import BaseInput from '../ui/BaseInput.vue'
import {useLoadedProgram} from '../composables/useLoadedProgram'
import {useDirectoryQuery} from '../composables/useDirectoryQuery'
import {confirmDelete, downloadText, suggestCopyPath} from './machineconfig/explorerActions'
import {Icon} from "../ui";
import { useFileThumbnails } from '../composables/useFileThumbnails'
import { useMachineOnline } from '../composables/useMachineOnline'
import ToolpathViewer from './ToolpathViewer.vue'
import { parseGcodeToolpath } from '../parsers/gcodeParser'
import type { ParsedSegment } from '../parsers/gcodeParser'
import { ensureEmbeddedThumbnail } from '../helpers/gcodeThumbnail'

const consoleStore = useConsoleStore()

// ``shallowRef``: a deep ref would unwrap the entity's private fields.
// The whole tree (folders + files at every depth), flat.
const files = shallowRef<FileEntry[]>([])
const isUploading = ref(false)
const ACCEPTED = '.ngc,.gcode,.nc'

// ---- Folder navigation ------------------------------------------ //

const currentDirectory = useDirectoryQuery('programsDir')
const breadcrumbs = computed(() => currentDirectory.value.split('/').filter(Boolean))
const inCurrent = (entry: FileEntry) => (entry.parent ?? '') === currentDirectory.value

const folders = computed(() =>
  files.value.filter((e) => e.isFolder && inCurrent(e)).sort((a, b) => a.name.localeCompare(b.name))
)

// Newest upload first — ``modified`` doubles as "uploaded at" since
// nc_files are write-once (Upload creates them, Edit rewrites the
// same timestamp forward, there's no separate "created" field).
const sortedFiles = computed(() =>
  files.value.filter((f) => f.isFile && inCurrent(f)).sort((a, b) => b.modifiedMs - a.modifiedMs)
)

function childCount(folder: FileEntry): number {
  return files.value.filter((e) => e.parent === folder.path).length
}

function openFolder(path: string) {
  currentDirectory.value = path
}

function goUp() {
  currentDirectory.value = breadcrumbs.value.slice(0, -1).join('/')
}

function goToCrumb(index: number) {
  currentDirectory.value = breadcrumbs.value.slice(0, index + 1).join('/')
}

function joinPath(directory: string, name: string) {
  return [directory, name].filter(Boolean).join('/')
}

// Load only works while the machine service (:8000) is up — the
// system service (:8001, always up) can list/edit/delete files but
// has no LinuxCNC interpreter to load a program into.
const { isMachineOnline } = useMachineOnline()
const loadBlockedTitle = 'Machine service is offline — start the machine to load a program.'

// ---- Slicer thumbnails + 3D toolpath preview ------------------- //
//
// Slicers (Cura / PrusaSlicer / Orca) embed a preview PNG at the top
// of the file as a base64 comment block; the backend extracts it
// (`GET /thumbnail/{path}`) and the list shows it as the row's
// icon. Clicking a row opens a preview modal: the embedded image on
// the left, the parsed toolpath (existing coordinate-viewer parser +
// a jog-free extracted renderer) on the right. Preview is read-only
// — nothing is written back.

const { thumbnails, ensure } = useFileThumbnails()

// Only the files of the open folder need their icon.
watch(sortedFiles, (list) => {
  for (const file of list) void ensure(file.path)
})

const previewFile = shallowRef<FileEntry | null>(null)
const previewLoading = ref(false)
const previewError = ref('')
const previewSegments = ref<ParsedSegment[]>([])

async function openPreview(file: FileEntry) {
  previewFile.value = file
  previewLoading.value = true
  previewError.value = ''
  previewSegments.value = []
  void ensure(file.path)
  try {
    const text = await readFileContent(file.path)
    previewSegments.value = parseGcodeToolpath(text)
  } catch (error) {
    previewError.value = `Failed to parse ${file.path}: ${describeError(error)}`
  } finally {
    previewLoading.value = false
  }
}

function closePreview() {
  previewFile.value = null
  previewSegments.value = []
  previewError.value = ''
}

// ---- Error-mapping helper -------------------------------------- //
//
// The generated client throws ``ApiError`` with ``body`` already
// parsed (FastAPI returns ``{"detail": "..."}`` for HTTPException).
// The shared :func:`describeErrorOr` helper handles every envelope
// shape (issue #99 structured error, FastAPI ``detail``, plain
// ``Error.message``) so a future shape change lives in one place.
const describeError = (error: unknown) => describeErrorOr(error, 'Unknown error');

// ---- File management: list / upload / delete / read -------------- //

async function fetchFiles() {
  try {
    files.value = await filesFacade.listFiles()
  } catch (error) {
    consoleStore.error(`Failed to fetch files: ${describeError(error)}`)
  }
}

async function readFileContent(filename: string) {
  // ``readFile`` throws on 404. Treat that as "brand-new file" so
  // the editor mounts with empty content instead of blocking the user.
  try {
    return await filesFacade.readFile(filename)
  } catch (error) {
    if (errorStatus(error) === 404) return ''
    throw error
  }
}

// Thumbnail embedding: if a file carries no slicer thumbnail, render
// one from its toolpath (top-down, like the slicers do) and prepend
// the standard '; thumbnail begin/end' comment block BEFORE storing —
// so the preview icon renders everywhere. Files that already have one
// are stored byte-for-byte. A ``File`` (not a plain ``Blob``!) is
// uploaded: a nameless Blob makes the multipart part default to the
// filename "blob". The ``File``'s ``name`` keeps the original name.
async function withThumbnail(file: File): Promise<File> {
  const rawText = await file.text()
  const segments = parseGcodeToolpath(rawText)
  const finalText = ensureEmbeddedThumbnail(rawText, segments)
  return new File([finalText], file.name, { type: 'text/plain' })
}

// Several files at once, into the open folder: each is uploaded on its
// own; a failure is reported for that file and the rest still go through.
async function uploadFiles(selected: File[]) {
  isUploading.value = true
  const directory = currentDirectory.value
  let uploaded = 0
  try {
    for (const file of selected) {
      try {
        const result = await filesFacade.uploadFile(file.name, await withThumbnail(file), directory)
        if (result.ok) uploaded++
        else consoleStore.error(`Upload of ${file.name} failed: ${result.failureReason}`)
      } catch (error) {
        consoleStore.error(`Upload of ${file.name} failed: ${describeError(error)}`)
      }
    }
    if (uploaded) consoleStore.success(`Uploaded ${uploaded} of ${selected.length} file(s)${directory ? ` to ${directory}` : ''}`)
    await fetchFiles()
  } finally {
    isUploading.value = false
  }
}

function rejectFiles(rejected: File[]) {
  consoleStore.error(`Not a G-code file (${ACCEPTED}): ${rejected.map((f) => f.name).join(', ')}`)
}

/** Report a facade result; refresh the list on success. */
async function afterChange(result: { ok: boolean; failureReason: string | null }, done: string, failed: string) {
  if (!result.ok) {
    consoleStore.error(`${failed}: ${result.failureReason}`)
    return
  }
  consoleStore.success(done)
  await fetchFiles()
}

async function deleteEntry(entry: FileEntry) {
  const { confirmed, recursive } = await confirmDelete(entry, files.value)
  if (!confirmed) return
  const result = await filesFacade.deleteFile(entry.path, recursive)
  await afterChange(result, `Deleted ${entry.path}`, `Failed to delete ${entry.path}`)
}

async function copyEntry(entry: FileEntry) {
  const taken = new Set(files.value.map((e) => e.path))
  const destination = window.prompt(`Copy ${entry.path} to`, suggestCopyPath(entry.path, taken))?.trim()
  if (!destination || destination === entry.path) return
  const result = await filesFacade.copyEntry(entry.path, destination)
  await afterChange(result, `Copied ${entry.path} -> ${destination}`, `Failed to copy ${entry.path}`)
}

async function moveEntry(entry: FileEntry) {
  const destination = window.prompt(`Move / rename ${entry.path} to`, entry.path)?.trim()
  if (!destination || destination === entry.path) return
  const result = await filesFacade.moveEntry(entry.path, destination)
  await afterChange(result, `Moved ${entry.path} -> ${destination}`, `Failed to move ${entry.path}`)
}

// ---- New folder (blue ⊕) ---------------------------------------- //

const folderDialogOpen = ref(false)
const newFolderName = ref('')

function openFolderDialog() {
  newFolderName.value = ''
  folderDialogOpen.value = true
}

async function createFolder() {
  const name = newFolderName.value.trim()
  if (!name) return
  const path = joinPath(currentDirectory.value, name)
  const result = await filesFacade.createFolder(path)
  folderDialogOpen.value = false
  await afterChange(result, `Created folder ${path}`, `Failed to create ${path}`)
}

// ---- Program lifecycle: load via ``progressFacade`` -------------- //
//
// Lifecycle calls live on the program module (``/api/v1/modules/program``)
// — different endpoint family than the file CRUD above, hence the
// separate facade. The button label is "Load" because it mirrors
// LinuxCNC's ``program_open`` (the "load" step in the two-step
// lifecycle); the operator still has to press Start in the
// dashboard widget to begin execution.

// The loaded program is highlighted (matched by path — base names are
// not unique across folders); its row offers Unload instead.
const { loadedPathAmong } = useLoadedProgram()
const loadedPath = computed(() => loadedPathAmong(files.value.filter((e) => e.isFile).map((e) => e.path)))
const isLoaded = (path: string) => loadedPath.value === path
const containsLoaded = (folder: FileEntry) => !!loadedPath.value?.startsWith(`${folder.path}/`)
/** File whose load / unload request is in flight. */
const busyFile = ref<string | null>(null)

async function loadFile(filename: string) {
  if (!isMachineOnline.value) return
  busyFile.value = filename
  try {
    consoleStore.command(`Loading file ${filename}...`)
    const result = await progressFacade.loadProgram(filename)
    if (result.ok) consoleStore.success(`Loaded ${filename} — press Start to begin.`)
    else consoleStore.error(`Failed to load ${filename}: ${result.failureReason}`)
  } finally {
    busyFile.value = null
  }
}

async function unloadFile(filename: string) {
  if (!isMachineOnline.value) return
  busyFile.value = filename
  try {
    const result = await progressFacade.unloadProgram()
    if (result.ok) consoleStore.info(`Unloaded ${filename}`)
    else consoleStore.error(`Failed to unload ${filename}: ${result.failureReason}`)
  } finally {
    busyFile.value = null
  }
}

// ---- Row "⋮" menus ---------------------------------------------- //

const ROW_MENU: ActionMenuItem[] = [
  { key: 'edit', label: 'Edit' },
  { key: 'download', label: 'Download' },
  { key: 'copy', label: 'Copy…', separated: true },
  { key: 'move', label: 'Move / rename…' },
  { key: 'delete', label: 'Delete', danger: true, separated: true },
]

const FOLDER_MENU: ActionMenuItem[] = [
  { key: 'open', label: 'Open' },
  { key: 'copy', label: 'Copy…', separated: true },
  { key: 'move', label: 'Move / rename…' },
  { key: 'delete', label: 'Delete', danger: true, separated: true },
]

async function onRowMenu(file: FileEntry, key: string) {
  if (key === 'edit') await editFile(file.path)
  else if (key === 'download') await downloadFile(file.path)
  else if (key === 'copy') await copyEntry(file)
  else if (key === 'move') await moveEntry(file)
  else if (key === 'delete') await deleteEntry(file)
}

async function onFolderMenu(folder: FileEntry, key: string) {
  if (key === 'open') openFolder(folder.path)
  else if (key === 'copy') await copyEntry(folder)
  else if (key === 'move') await moveEntry(folder)
  else if (key === 'delete') await deleteEntry(folder)
}

// ---- Download -------------------------------------------------- //
//
// The programs router has no dedicated download endpoint — reuse the
// same content read the editor/preview already use and hand the
// browser a Blob (``createObjectURL`` in ``downloadText``).

async function downloadFile(filename: string) {
  try {
    downloadText(filename.split('/').pop() || filename, await readFileContent(filename))
  } catch (error) {
    consoleStore.error(`Failed to download ${filename}: ${describeError(error)}`)
  }
}

// ---- Route to EditorView --------------------------------------- //
//
// We don't mount ``Editor`` here — that hid the rest of the app.
// Instead, push to ``/editor?source=programs&name=...`` so
// ``EditorView`` reads the (source, name) pair from the URL and
// renders the full layout (header, sidebar, content) around the
// editor. The store knows how to dispatch the read by source, so
// the filename extension is no longer used to decide routing.

async function editFile(filename: string) {
  await openInEditor({source: 'programs', name: filename})
}

onMounted(() => {
  fetchFiles()
})
</script>

<template>
  <!-- Full-page dedicated view: fill the parent container end-to-end
       instead of being a small dashboard card. -->
  <FileDropZone
      v-slot="{ openPicker }"
      :target="currentDirectory || 'G-code files'"
      :accept="ACCEPTED"
      :disabled="isUploading"
      class="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden w-full h-full flex flex-col"
      @files="uploadFiles"
      @rejected="rejectFiles"
  >
    <!-- Header & Upload -->
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex  items-center shrink-0">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        <span class="mr-2">📂</span> G-Code Files
      </h2>

      <div>
        <BaseButton
            variant="primary"
            class="ml-4"
            :loading="isUploading"
            data-test="file-upload"
            @click="openPicker"
        >
          <span class="mr-1">⬆</span> {{ isUploading ? 'Uploading...' : 'Upload' }}
        </BaseButton>
      </div>
    </div>

    <!-- Folder path -->
    <nav class="flex min-h-11 shrink-0 items-center gap-2 border-b border-gray-700 px-3 py-2 text-sm" data-test="programs-breadcrumbs">
      <BaseButton variant="ghost" size="sm" :disabled="!currentDirectory" title="Up one folder" aria-label="Up one folder" @click="goUp">
        <template #icon><Icon name="chevronLeft" class="h-4 w-4" /></template>
      </BaseButton>
      <button type="button" class="font-mono text-blue-300 hover:text-blue-200" @click="openFolder('')">nc_files</button>
      <template v-for="(crumb, index) in breadcrumbs" :key="`${crumb}-${index}`">
        <span class="text-gray-600">/</span>
        <button type="button" class="truncate font-mono text-gray-300 hover:text-white" @click="goToCrumb(index)">{{ crumb }}</button>
      </template>
    </nav>

    <!-- File List -->
    <div class="flex-1 overflow-y-auto p-4 pb-24 bg-gray-700/20">
      <table v-if="folders.length || sortedFiles.length" class="w-full text-left text-sm text-gray-300">
        <thead class="text-xs uppercase text-gray-400 border-b border-gray-600">
        <tr>
          <th class="py-2 px-2">Preview</th>
          <th class="py-2 px-2">Filename</th>
          <th class="py-2 px-2">Size</th>
          <th class="py-2 px-2">Uploaded</th>
          <th class="py-2 px-2 text-right">Actions</th>
        </tr>
        </thead>
        <tbody>
        <tr
            v-for="folder in folders"
            :key="folder.path"
            class="border-b border-gray-700/50 cursor-pointer hover:bg-gray-700/40"
            :data-test="`folder-row-${folder.path}`"
            @click="openFolder(folder.path)"
        >
          <td class="py-2 px-2">
            <span class="flex h-10 w-14 items-center justify-center rounded border border-gray-600 bg-gray-900 text-xl">📁</span>
          </td>
          <td class="py-2 px-2 font-mono">
            {{ folder.name }}
            <span
                v-if="containsLoaded(folder)"
                class="ml-2 rounded border border-blue-500 px-1.5 py-0.5 align-middle font-sans text-[10px] uppercase tracking-widest text-blue-200"
                title="The loaded program is in this folder"
            >loaded inside</span>
          </td>
          <td class="py-2 px-2 text-gray-400">{{ childCount(folder) }} item(s)</td>
          <td class="py-2 px-2 text-gray-400">{{ formatDate(folder.modified) }}</td>
          <td class="py-2 px-2" @click.stop>
            <div class="flex items-center justify-end gap-2">
              <ActionMenu :items="FOLDER_MENU" :test-id="`folder-${folder.path}`" @select="onFolderMenu(folder, $event)" />
            </div>
          </td>
        </tr>
        <tr
            v-for="file in sortedFiles"
            :key="file.path"
            class="border-b border-gray-700/50 cursor-pointer"
            :class="isLoaded(file.path) ? 'bg-blue-900/40 ring-1 ring-inset ring-blue-500/60' : 'hover:bg-gray-700/40'"
            :data-loaded="isLoaded(file.path) || undefined"
            :data-test="`file-row-${file.path}`"
            @click="openPreview(file)"
        >
          <td class="py-2 px-2">
            <img
                v-if="thumbnails[file.path]?.dataUrl"
                :src="thumbnails[file.path]?.dataUrl ?? ''"
                :alt="`Preview of ${file.name}`"
                class="h-10 w-14 rounded border border-gray-600 object-contain bg-gray-900"
                :data-test="`file-thumb-${file.name}`"
            />
            <span
                v-else
                class="flex h-10 w-14 items-center justify-center rounded border border-gray-600 bg-gray-900 text-lg"
                :data-test="`file-thumb-${file.name}`"
                title="No embedded thumbnail"
            >📄</span>
          </td>
          <td class="py-2 px-2 font-mono" :class="isLoaded(file.path) ? 'font-semibold text-blue-300' : ''">
            {{ file.name }}
            <span
                v-if="isLoaded(file.path)"
                class="ml-2 rounded border border-blue-500 px-1.5 py-0.5 align-middle font-sans text-[10px] uppercase tracking-widest text-blue-200"
            >loaded</span>
          </td>
          <td class="py-2 px-2">{{ formatSize(file.sizeBytes) }}</td>
          <td class="py-2 px-2 text-gray-400">{{ formatDate(file.modified) }}</td>
          <td class="py-2 px-2" @click.stop>
            <div class="flex items-center justify-end gap-2">
              <BaseButton
                  size="sm"
                  :variant="isLoaded(file.path) ? 'danger' : 'primary'"
                  :disabled="!isMachineOnline || busyFile !== null"
                  :loading="busyFile === file.path"
                  :title="isMachineOnline ? undefined : loadBlockedTitle"
                  :data-test="`file-row-load-${file.path}`"
                  @click="isLoaded(file.path) ? unloadFile(file.path) : loadFile(file.path)"
              >{{ isLoaded(file.path) ? 'Unload' : 'Load' }}</BaseButton>
              <ActionMenu :items="ROW_MENU" :test-id="`file-${file.path}`" @select="onRowMenu(file, $event)" />
            </div>
          </td>
        </tr>
        </tbody>
      </table>

      <div
          v-else
          class="flex flex-col items-center justify-center py-12 text-gray-500"
      >
        <p class="text-sm font-semibold">{{ currentDirectory ? 'This folder is empty' : 'No G-code files yet' }}</p>
        <p class="text-xs mt-1">Drop files here, use the Upload button, or ⊕ to create a folder.</p>
      </div>
    </div>

    <!-- New folder: blue circle with a white plus, bottom-right corner -->
    <button
        type="button"
        class="absolute bottom-6 right-6 z-10 flex h-12 w-12 items-center justify-center rounded-full bg-blue-600 text-3xl leading-none text-white hover:bg-blue-500"
        title="Create folder"
        aria-label="Create folder"
        data-test="programs-new-folder"
        @click="openFolderDialog"
    >+</button>

    <div
        v-if="folderDialogOpen"
        class="absolute inset-0 z-30 flex items-center justify-center bg-black/70 p-4"
        data-test="programs-new-folder-dialog"
        @click.self="folderDialogOpen = false"
    >
      <form class="w-full max-w-sm space-y-4 rounded-lg border border-gray-600 bg-gray-800 p-4" @submit.prevent="createFolder">
        <h3 class="font-semibold text-gray-100">New folder in {{ currentDirectory || 'nc_files' }}</h3>
        <BaseInput v-model="newFolderName" autofocus type="text" placeholder="Folder name, e.g. bracket-v2" class="w-full font-mono" />
        <div class="flex justify-end gap-2">
          <BaseButton variant="secondary" @click="folderDialogOpen = false">Cancel</BaseButton>
          <BaseButton variant="primary" type="submit" :disabled="!newFolderName.trim()" data-test="programs-new-folder-create">Create</BaseButton>
        </div>
      </form>
    </div>

    <!-- Preview modal: slicer thumbnail + 3D toolpath (read-only) -->
    <Teleport to="body">
      <div
          v-if="previewFile"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          data-test="file-preview-modal"
          @click.self="closePreview"
      >
        <div class="w-full max-w-4xl rounded-lg border border-gray-600 bg-gray-800">
          <header class="flex items-center justify-between gap-2 border-b border-gray-700 px-4 py-3">
            <div class="min-w-0">
              <h3 class="truncate font-mono text-sm font-semibold text-gray-100">{{ previewFile.path }}</h3>
              <p class="text-xs text-gray-500">
                {{ formatSize(previewFile.sizeBytes) }}
                <template v-if="!previewLoading && !previewError">
                  · {{ previewSegments.length }} moves
                </template>
              </p>
            </div>
            <div class="flex shrink-0 items-center gap-3">
              <span v-if="!isMachineOnline" class="text-xs text-gray-500" data-test="preview-load-offline-hint">
                Machine offline
              </span>
              <BaseButton
                  variant="success"
                  size="sm"
                  :disabled="!isMachineOnline"
                  :title="isMachineOnline ? undefined : loadBlockedTitle"
                  @click="loadFile(previewFile.path)"
                  :data-test="`file-load-${previewFile.path}`"
              >
                <Icon name="refresh"/>
                Load
              </BaseButton>
              <button class="text-gray-400 hover:text-gray-200" aria-label="Close preview" @click="closePreview">
                <Icon name="close" class="h-5 w-5" />
              </button>
            </div>
          </header>

          <div class="grid grid-cols-1 gap-4 p-4 md:grid-cols-3">
            <!-- Left: embedded slicer image -->
            <div class="flex flex-col items-center justify-center gap-3">
              <img
                  v-if="thumbnails[previewFile.path]?.dataUrl"
                  :src="thumbnails[previewFile.path]?.dataUrl ?? ''"
                  :alt="`Slicer preview of ${previewFile.name}`"
                  class="max-h-64 w-full rounded border border-gray-600 object-contain bg-gray-900"
                  data-test="preview-thumb"
              />
              <span
                  v-else
                  class="flex h-40 w-full items-center justify-center rounded border border-dashed border-gray-600 bg-gray-900 text-4xl text-gray-600"
                  data-test="preview-thumb-empty"
                  title="This file has no embedded slicer thumbnail"
              >📄</span>
              <p class="text-center text-xs text-gray-500">
                Thumbnail embedded by the slicer.
                The 3D view is parsed from the G-code itself.
              </p>
            </div>

            <!-- Right: 3D toolpath (coordinate-viewer parser + renderer) -->
            <div class="md:col-span-2">
              <div class="relative h-[400px]">
                <p
                    v-if="previewLoading"
                    class="absolute inset-0 flex items-center justify-center text-sm text-gray-500"
                >Parsing toolpath…</p>
                <p
                    v-else-if="previewError"
                    class="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-red-300"
                >{{ previewError }}</p>
                <p
                    v-else-if="previewSegments.length === 0"
                    class="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-gray-500"
                >No motion segments found in this file.</p>
                <ToolpathViewer v-else :segments="previewSegments" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </FileDropZone>
</template>