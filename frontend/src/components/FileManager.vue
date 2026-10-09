<script setup lang="ts">
// File manager — G-code file list, upload, delete, load, edit.
// File calls go through ``filesFacade``, Load through
// ``progressFacade``; rows are the shared ``FileEntry`` entity.
// Upload is the shared ``FileDropZone`` (drag & drop or picker,
// several files at once). Routes the user to ``EditorView`` on Edit
// so the page chrome (sidebar / header) stays visible while editing.

import {ref, shallowRef, computed, onMounted, watch} from 'vue'

import {useConsoleStore} from '../stores/console'
import {openInEditor} from '../helpers/openInEditor'
import {describeErrorOr, errorStatus} from '../core/error-format'
import {filesFacade} from '../facades/filesFacade'
import {progressFacade} from '../facades/progressFacade'
import type {FileEntry} from '../entities/files'
import {formatFileDate as formatDate, formatFileSize as formatSize} from '../helpers/fileFormat'
import {BaseButton, FileDropZone} from '../ui/index.ts'
import {Icon} from "../ui";
import { useFileThumbnails } from '../composables/useFileThumbnails'
import { useMachineOnline } from '../composables/useMachineOnline'
import ToolpathViewer from './ToolpathViewer.vue'
import { parseGcodeToolpath } from '../parsers/gcodeParser'
import type { ParsedSegment } from '../parsers/gcodeParser'
import { ensureEmbeddedThumbnail } from '../helpers/gcodeThumbnail'

const consoleStore = useConsoleStore()

// ``shallowRef``: a deep ref would unwrap the entity's private fields.
const files = shallowRef<FileEntry[]>([])
const isUploading = ref(false)
const ACCEPTED = '.ngc,.gcode,.nc'

// Newest upload first — ``modified`` doubles as "uploaded at" since
// nc_files are write-once (Upload creates them, Edit rewrites the
// same timestamp forward, there's no separate "created" field).
const sortedFiles = computed(() =>
  files.value.filter((f) => f.isFile).sort((a, b) => b.modifiedMs - a.modifiedMs)
)

// Load only works while the machine service (:8000) is up — the
// system service (:8001, always up) can list/edit/delete files but
// has no LinuxCNC interpreter to load a program into.
const { isMachineOnline } = useMachineOnline()
const loadBlockedTitle = 'Machine service is offline — start the machine to load a program.'

// ---- Slicer thumbnails + 3D toolpath preview ------------------- //
//
// Slicers (Cura / PrusaSlicer / Orca) embed a preview PNG at the top
// of the file as a base64 comment block; the backend extracts it
// (`GET /thumbnail/{filename}`) and the list shows it as the row's
// icon. Clicking a row opens a preview modal: the embedded image on
// the left, the parsed toolpath (existing coordinate-viewer parser +
// a jog-free extracted renderer) on the right. Preview is read-only
// — nothing is written back.

const { thumbnails, ensure } = useFileThumbnails()

watch(files, (list) => {
  for (const file of list) void ensure(file.name)
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
  void ensure(file.name)
  try {
    const text = await readFileContent(file.name)
    previewSegments.value = parseGcodeToolpath(text)
  } catch (error) {
    previewError.value = `Failed to parse ${file.name}: ${describeError(error)}`
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

// Several files at once: each is uploaded on its own; a failure is
// reported for that file and the rest still go through.
async function uploadFiles(selected: File[]) {
  isUploading.value = true
  let uploaded = 0
  try {
    for (const file of selected) {
      try {
        const result = await filesFacade.uploadFile(file.name, await withThumbnail(file))
        if (result.ok) uploaded++
        else consoleStore.error(`Upload of ${file.name} failed: ${result.failureReason}`)
      } catch (error) {
        consoleStore.error(`Upload of ${file.name} failed: ${describeError(error)}`)
      }
    }
    if (uploaded) consoleStore.success(`Uploaded ${uploaded} of ${selected.length} file(s)`)
    await fetchFiles()
  } finally {
    isUploading.value = false
  }
}

function rejectFiles(rejected: File[]) {
  consoleStore.error(`Not a G-code file (${ACCEPTED}): ${rejected.map((f) => f.name).join(', ')}`)
}

async function deleteFile(filename: string) {
  if (!confirm(`Are you sure you want to delete ${filename}?`)) return

  const result = await filesFacade.deleteFile(filename)
  if (!result.ok) {
    consoleStore.error(`Failed to delete ${filename}: ${result.failureReason}`)
    return
  }
  consoleStore.success(`Deleted file ${filename}`)
  await fetchFiles()
}

// ---- Program lifecycle: load via ``progressFacade`` -------------- //
//
// Lifecycle calls live on the program module (``/api/v1/modules/program``)
// — different endpoint family than the file CRUD above, hence the
// separate facade. The button label is "Load" because it mirrors
// LinuxCNC's ``program_open`` (the "load" step in the two-step
// lifecycle); the operator still has to press Start in the
// dashboard widget to begin execution.

async function loadFile(filename: string) {
  if (!isMachineOnline.value) return
  consoleStore.command(`Loading file ${filename}...`)
  const result = await progressFacade.loadProgram(filename)
  if (result.ok) consoleStore.success(`Loaded ${filename} — press Start to begin.`)
  else consoleStore.error(`Failed to load ${filename}: ${result.failureReason}`)
}

// ---- Download -------------------------------------------------- //
//
// The programs router has no dedicated download endpoint — reuse the
// same content read the editor/preview already use and hand the
// browser a Blob, mirroring MachinesExplorer.vue's downloadMachineFile.

async function downloadFile(filename: string) {
  try {
    const content = await readFileContent(filename)
    const blob = new Blob([content], {type: 'text/plain;charset=utf-8'})
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.style.display = 'none'
    document.body.appendChild(anchor)
    anchor.click()
    document.body.removeChild(anchor)
    URL.revokeObjectURL(url)
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
      target="G-code files"
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

    <!-- File List -->
    <div class="flex-1 overflow-y-auto p-4 bg-gray-700/20">
      <table v-if="files.length" class="w-full text-left text-sm text-gray-300">
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
            v-for="file in sortedFiles"
            :key="file.name"
            class="border-b border-gray-700/50 hover:bg-gray-700/40 cursor-pointer"
            @click="openPreview(file)"
        >
          <td class="py-2 px-2">
            <img
                v-if="thumbnails[file.name]?.dataUrl"
                :src="thumbnails[file.name]?.dataUrl ?? ''"
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
          <td class="py-2 px-2 font-mono">{{ file.name }}</td>
          <td class="py-2 px-2">{{ formatSize(file.sizeBytes) }}</td>
          <td class="py-2 px-2 text-gray-400">{{ formatDate(file.modified) }}</td>
          <td class="py-2 px-2 text-right space-x-2" @click.stop>

            <BaseButton
                variant="ghost"
                size="sm"
                @click="downloadFile(file.name)"
                :data-test="`file-download-${file.name}`"
                title="Download"
                aria-label="Download"
            >↓</BaseButton>
            <BaseButton
                variant="primary"
                size="sm"
                @click="editFile(file.name)"
                :data-test="`file-edit-${file.name}`"
            >
              <Icon name="edit"/>
              Edit
            </BaseButton>



            <BaseButton
                variant="secondary"
                size="sm"
                @click="deleteFile(file.name)"
                :data-test="`file-delete-${file.name}`"
            >
              <Icon name="trash" />
              Delete
            </BaseButton>
          </td>
        </tr>
        </tbody>
      </table>

      <div
          v-else
          class="flex flex-col items-center justify-center py-12 text-gray-500"
      >
        <p class="text-sm font-semibold">No G-code files yet</p>
        <p class="text-xs mt-1">Drop files here or use the Upload button.</p>
      </div>
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
              <h3 class="truncate font-mono text-sm font-semibold text-gray-100">{{ previewFile.name }}</h3>
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
                  @click="loadFile(previewFile.name)"
                  :data-test="`file-load-${previewFile.name}`"
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
                  v-if="thumbnails[previewFile.name]?.dataUrl"
                  :src="thumbnails[previewFile.name]?.dataUrl ?? ''"
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