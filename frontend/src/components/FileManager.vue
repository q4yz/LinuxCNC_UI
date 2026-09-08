<script setup lang="ts">
// File manager — G-code file list, upload, delete, load, edit.
// All HTTP calls go through the generated OpenAPI client so the
// paths, error mapping, and types stay in sync with the backend
// schema. Routes the user to ``EditorView`` on Edit so the page
// chrome (sidebar / header) stays visible while editing.

import {ref, onMounted, watch} from 'vue'

import {
  ModulesProgramService,
  ProgramFilesService,
} from '../../generated/api/index.ts'
import {useConsoleStore} from '../stores/console'
import {openInEditor} from '../helpers/openInEditor'
import {describeErrorOr} from '../core/error-format'
import {ApiError} from '../../generated/api/core/ApiError'
import type {FileInfo} from '../../generated/api/models/FileInfo'
import {BaseButton} from '../ui/index.ts'
import {Icon} from "../ui";
import { useFileThumbnails } from '../composables/useFileThumbnails'
import ToolpathViewer from './ToolpathViewer.vue'
import { parseGcodeToolpath } from '../parsers/gcodeParser'
import type { ParsedSegment } from '../parsers/gcodeParser'
import { ensureEmbeddedThumbnail } from '../helpers/gcodeThumbnail'

const consoleStore = useConsoleStore()

const files = ref<FileInfo[]>([])
const isUploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

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
  for (const file of list) void ensure(file.filename)
})

const previewFile = ref<FileInfo | null>(null)
const previewLoading = ref(false)
const previewError = ref('')
const previewSegments = ref<ParsedSegment[]>([])

async function openPreview(file: FileInfo) {
  previewFile.value = file
  previewLoading.value = true
  previewError.value = ''
  previewSegments.value = []
  void ensure(file.filename)
  try {
    const text = await readFileContent(file.filename)
    previewSegments.value = parseGcodeToolpath(text)
  } catch (error) {
    previewError.value = `Failed to parse ${file.filename}: ${describeError(error)}`
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
//
// Every call goes through ``ProgramFilesService`` (the OpenAPI-
// generated client for the ``/api/v1/programs`` router — tag
// ``Program Files``). ``ModulesProgramService`` stays for the
// lifecycle calls (``runProgram`` etc.) that live on the program
// module — different endpoint family, different service.

async function fetchFiles() {
  try {
    files.value = await ProgramFilesService.listFiles()
  } catch (error) {
    consoleStore.error(`Failed to fetch files: ${describeError(error)}`)
  }
}

async function readFileContent(filename: string) {
  // ``readFile`` throws ``ApiError`` on 404. Treat that as
  // "brand-new file" so the editor mounts with empty content
  // instead of blocking the user.
  try {
    return await ProgramFilesService.readFile(filename)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return ''
    throw error
  }
}

async function handleUpload(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return

  isUploading.value = true
  try {
    // Thumbnail embedding: if the file carries no slicer thumbnail,
    // render one from its toolpath (top-down, like the slicers do)
    // and prepend the standard '; thumbnail begin/end' comment block
    // BEFORE storing — so the preview icon renders everywhere. Files
    // that already have one are stored byte-for-byte.
    const rawText = await file.text()
    const segments = parseGcodeToolpath(rawText)
    const finalText = ensureEmbeddedThumbnail(rawText, segments)
    // ``Body_uploadFile.file`` is typed ``string`` by the codegen
    // but the request layer's ``isBlob`` check accepts ``Blob`` and
    // ``File`` instances at runtime (``/^(Blob|File)$/`` on the
    // constructor name) — cast through ``unknown`` so TypeScript is
    // happy. A ``File`` (not a plain ``Blob``!) is required: a
    // nameless Blob makes the multipart part default to the filename
    // "blob", and the backend stores the file under that name. The
    // ``File``'s ``name`` keeps the original filename intact.
    const payload = new File([finalText], file.name, { type: 'text/plain' })
    await ProgramFilesService.uploadFile({
      file: payload as unknown as string
    })
    consoleStore.success(`Successfully uploaded ${file.name}`)
    await fetchFiles()
  } catch (error) {
    consoleStore.error(`Upload failed: ${describeError(error)}`)
  } finally {
    isUploading.value = false
    // Reset input so the same file can be uploaded again if needed
    if (fileInput.value) fileInput.value.value = ''
  }
}

function triggerFileInput() {
  if (fileInput.value) fileInput.value.click()
}

async function deleteFile(filename: string) {
  if (!confirm(`Are you sure you want to delete ${filename}?`)) return

  try {
    await ProgramFilesService.deleteFile(filename)
    consoleStore.success(`Deleted file ${filename}`)
    await fetchFiles()
  } catch (error) {
    consoleStore.error(`Failed to delete ${filename}: ${describeError(error)}`)
  }
}

// ---- Program lifecycle: load + run via ``ModulesProgramService`` -- //
//
// Lifecycle calls live on the program module (``/api/v1/modules/program``)
// — different endpoint family than the file CRUD above, hence the
// separate service. The button label is "Load" because it mirrors
// LinuxCNC's ``program_open`` (the "load" step in the two-step
// lifecycle); the operator still has to press Start in the
// dashboard widget to begin execution.

async function loadFile(filename: string) {
  try {
    consoleStore.command(`Loading file ${filename}...`)
    await ModulesProgramService.loadProgram({filename})
    consoleStore.success(`Loaded ${filename} — press Start to begin.`)
  } catch (error) {
    consoleStore.error(`Failed to load ${filename}: ${describeError(error)}`)
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

function formatSize(bytes: number) {
  if (bytes < 1024) return bytes + ' B'
  else if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB'
  else return (bytes / 1048576).toFixed(1) + ' MB'
}

onMounted(() => {
  fetchFiles()
})
</script>

<template>
  <!-- Full-page dedicated view: fill the parent container end-to-end
       instead of being a small dashboard card. -->
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden w-full h-full flex flex-col">
    <!-- Header & Upload -->
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex  items-center shrink-0">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        <span class="mr-2">📂</span> G-Code Files
      </h2>

      <div>
        <input
            type="file"
            ref="fileInput"
            class="hidden"
            accept=".ngc,.gcode,.nc"
            @change="handleUpload"
        />
        <BaseButton
            variant="primary"
            class="ml-4"
            :loading="isUploading"
            @click="triggerFileInput"
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
          <th class="py-2 px-2 text-right">Actions</th>
        </tr>
        </thead>
        <tbody>
        <tr
            v-for="file in files"
            :key="file.filename"
            class="border-b border-gray-700/50 hover:bg-gray-700/40 cursor-pointer"
            @click="openPreview(file)"
        >
          <td class="py-2 px-2">
            <img
                v-if="thumbnails[file.filename]?.dataUrl"
                :src="thumbnails[file.filename]?.dataUrl ?? ''"
                :alt="`Preview of ${file.filename}`"
                class="h-10 w-14 rounded border border-gray-600 object-contain bg-gray-900"
                :data-test="`file-thumb-${file.filename}`"
            />
            <span
                v-else
                class="flex h-10 w-14 items-center justify-center rounded border border-gray-600 bg-gray-900 text-lg"
                :data-test="`file-thumb-${file.filename}`"
                title="No embedded thumbnail"
            >📄</span>
          </td>
          <td class="py-2 px-2 font-mono">{{ file.filename }}</td>
          <td class="py-2 px-2">{{ formatSize(file.size_bytes || 0) }}</td>
          <td class="py-2 px-2 text-right space-x-2" @click.stop>

            <BaseButton
                variant="success"
                size="sm"
                @click="loadFile(file.filename)"
                :data-test="`file-load-${file.filename}`"
            >
              <Icon name="refresh"/>
              Load

            </BaseButton>
            <BaseButton
                variant="primary"
                size="sm"
                @click="editFile(file.filename)"
                :data-test="`file-edit-${file.filename}`"
            >
              <Icon name="edit"/>
              Edit
            </BaseButton>



            <BaseButton
                variant="secondary"
                size="sm"
                @click="deleteFile(file.filename)"
                :data-test="`file-delete-${file.filename}`"
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
        <p class="text-xs mt-1">Use the Upload button to add your first file.</p>
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
        <div class="w-full max-w-4xl rounded-lg border border-gray-600 bg-gray-800 shadow-2xl">
          <header class="flex items-center justify-between gap-2 border-b border-gray-700 px-4 py-3">
            <div class="min-w-0">
              <h3 class="truncate font-mono text-sm font-semibold text-gray-100">{{ previewFile.filename }}</h3>
              <p class="text-xs text-gray-500">
                {{ formatSize(previewFile.size_bytes || 0) }}
                <template v-if="!previewLoading && !previewError">
                  · {{ previewSegments.length }} moves
                </template>
              </p>
            </div>
            <button class="text-gray-400 hover:text-gray-200" aria-label="Close preview" @click="closePreview">
              <Icon name="close" class="h-5 w-5" />
            </button>
          </header>

          <div class="grid grid-cols-1 gap-4 p-4 md:grid-cols-3">
            <!-- Left: embedded slicer image -->
            <div class="flex flex-col items-center justify-center gap-3">
              <img
                  v-if="thumbnails[previewFile.filename]?.dataUrl"
                  :src="thumbnails[previewFile.filename]?.dataUrl ?? ''"
                  :alt="`Slicer preview of ${previewFile.filename}`"
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
  </div>
</template>