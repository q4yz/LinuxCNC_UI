<script setup>
// File manager — G-code file list, upload, delete, load, edit.
// All HTTP calls go through the generated OpenAPI client so the
// paths, error mapping, and types stay in sync with the backend
// schema. Routes the user to ``EditorView`` on Edit so the page
// chrome (sidebar / header) stays visible while editing.

import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import {
  ModulesProgramService,
  ProgramFilesService,
} from '../../generated/api/index.ts'
import { ApiError } from '../../generated/api/core/ApiError'
import { useConsoleStore } from '../stores/console'
import { useEditorStore } from '../stores/editor'

const router = useRouter()
const consoleStore = useConsoleStore()
const editorStore = useEditorStore()

const files = ref([])
const isUploading = ref(false)
const fileInput = ref(null)

// ---- Error-mapping helper -------------------------------------- //
//
// The generated client throws ``ApiError`` with ``body`` already
// parsed (FastAPI returns ``{"detail": "..."}`` for HTTPException).
// Fall back to ``statusText`` / ``message`` so every error path
// surfaces something operator-readable instead of ``[object Object]``.

function describeError(error) {
  if (!error) return 'Unknown error'
  if (error instanceof ApiError) {
    return (
      error.body?.detail ||
      error.body?.message ||
      error.statusText ||
      error.message ||
      `HTTP ${error.status}`
    )
  }
  return error.message || String(error)
}

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

async function readFileContent(filename) {
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

async function handleUpload(event) {
  const file = event.target.files[0]
  if (!file) return

  isUploading.value = true
  try {
    // ``Body_uploadFile.file`` is typed ``string`` by the codegen
    // but the request layer's ``isBlob`` check accepts ``File``
    // instances at runtime — see ``core/request.ts::isBlob``.
    // Cast through ``unknown`` so TypeScript is happy and the
    // request still sends a proper multipart upload.
    await ProgramFilesService.uploadFile({
      file: file
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

async function deleteFile(filename) {
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

async function loadFile(filename) {
  try {
    consoleStore.command(`Loading file ${filename}...`)
    await ModulesProgramService.loadProgram({ filename })
    consoleStore.success(`Loaded ${filename} — press Start to begin.`)
  } catch (error) {
    consoleStore.error(`Failed to load ${filename}: ${describeError(error)}`)
  }
}

// ---- Editor mode helper ---------------------------------------- //
//
// Pick the right Editor mode based on the file extension. G-code
// gets ``"gcode"``; INI/Klipper config files get ``"config"``.
// ``Editor.vue`` uses these to select its syntax-highlight pack.

function modeForFilename(filename) {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.gcode') || lower.endsWith('.ngc') || lower.endsWith('.nc')) {
    return 'gcode'
  }
  if (
    lower.endsWith('.cfg') ||
    lower.endsWith('.ini') ||
    lower.endsWith('.conf')
  ) {
    return 'config'
  }
  return 'text'
}

// ---- Route to EditorView --------------------------------------- //
//
// We don't mount ``Editor`` here — that hid the rest of the app.
// Instead, write the filename / mode / content to the shared
// ``editor`` Pinia store and ``router.push`` to ``/config`` so
// ``EditorView`` reads the state and renders the full layout
// (header, sidebar, content) around the editor.
//
// The file content is fetched up-front when present so the
// Editor mounts with text already in hand instead of flashing
// a loading state on every open. If the read fails the user
// still navigates — ``EditorView`` will fall back to its
// ``onMounted`` behaviour.

async function editFile(filename) {
  const mode = modeForFilename(filename)
  let content = ''
  try {
    content = await readFileContent(filename)
  } catch (error) {
    consoleStore.error(`Failed to read ${filename}: ${describeError(error)}`)
  }
  editorStore.open(filename, false, mode, content ?? '')
  router.push({ name: 'config' })
}

function formatSize(bytes) {
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
        <button
          type="button"
          class="bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded text-sm font-semibold flex items-center ml-4"
          @click="triggerFileInput"
          :disabled="isUploading"
        >
          <span class="mr-1">⬆</span> {{ isUploading ? 'Uploading...' : 'Upload' }}
        </button>
      </div>
    </div>

    <!-- File List -->
    <div class="flex-1 overflow-y-auto p-4 bg-gray-700/20">
      <table v-if="files.length" class="w-full text-left text-sm text-gray-300">
        <thead class="text-xs uppercase text-gray-400 border-b border-gray-600">
          <tr>
            <th class="py-2 px-2">Filename</th>
            <th class="py-2 px-2">Size</th>
            <th class="py-2 px-2 text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="file in files"
            :key="file.filename"
            class="border-b border-gray-700/50 hover:bg-gray-700/40"
          >
            <td class="py-2 px-2 font-mono">{{ file.filename }}</td>
            <td class="py-2 px-2">{{ formatSize(file.size_bytes || 0) }}</td>
            <td class="py-2 px-2 text-right space-x-2">
              <button
                type="button"
                class="text-blue-400 hover:text-blue-300 font-semibold"
                @click="editFile(file.filename)"
              >
                Edit
              </button>
              <button
                type="button"
                class="text-green-400 hover:text-green-300 font-semibold"
                @click="loadFile(file.filename)"
              >
                Load
              </button>
              <button
                type="button"
                class="text-red-400 hover:text-red-300 font-semibold"
                @click="deleteFile(file.filename)"
              >
                Delete
              </button>
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
  </div>
</template>