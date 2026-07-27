<script setup>
import { ref, onMounted } from 'vue'
import { NcFilesService } from '../../generated/api/services/NcFilesService'
import { useConsoleStore } from '../stores/console'

// FileManager is now a full-page dedicated view. The parent
// (``FilesView``) is expected to mount it inside a container that
// stretches edge-to-edge; the wrapper fills whatever space it is given
// rather than the previous fixed-height card.

const files = ref([])
const isUploading = ref(false)
const consoleStore = useConsoleStore()
const fileInput = ref(null)

// Emit ``edit`` events so the parent view can open the file in the
// full-screen ``ConfigEditor``. The component never imports the editor
// directly — that keeps it reusable and avoids prop-drilling the
// editor state through multiple layers.
const emit = defineEmits(['edit'])

const fetchFiles = async () => {
  try {
    files.value = await NcFilesService.listFiles()
  } catch (error) {
    consoleStore.addMessage(`Failed to fetch files: ${error.message}`, 'error')
  }
}

const handleUpload = async (event) => {
  const file = event.target.files[0]
  if (!file) return

  isUploading.value = true
  try {
    await NcFilesService.uploadFile({ file })
    consoleStore.addMessage(`Successfully uploaded ${file.name}`, 'success')
    await fetchFiles()
  } catch (error) {
    consoleStore.addMessage(`Upload failed: ${error.message}`, 'error')
  } finally {
    isUploading.value = false
    // Reset input so the same file can be uploaded again if needed
    if (fileInput.value) fileInput.value.value = ''
  }
}

const triggerFileInput = () => {
  if (fileInput.value) fileInput.value.click()
}

const deleteFile = async (filename) => {
  if (!confirm(`Are you sure you want to delete ${filename}?`)) return

  try {
    await NcFilesService.deleteFile(filename)
    consoleStore.addMessage(`Deleted file ${filename}`, 'success')
    await fetchFiles()
  } catch (error) {
    consoleStore.addMessage(`Failed to delete ${filename}: ${error.message}`, 'error')
  }
}

const loadFile = async (filename) => {
  try {
    consoleStore.addMessage(`Loading file ${filename}...`, 'command')
    await NcFilesService.loadProgram({ filename })
    consoleStore.addMessage(`Loaded ${filename}`, 'success')
  } catch (error) {
    consoleStore.addMessage(`Failed to load ${filename}: ${error.message}`, 'error')
  }
}

const editFile = (filename) => {
  // Bubble the request up to the parent view, which owns the
  // full-screen editor and already knows how to mount it.
  emit('edit', filename)
}

const formatSize = (bytes) => {
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
       instead of being a small dashboard card. ``h-full`` + ``w-full``
       means the layout is driven by whichever slot this component is
       dropped into (the Files view, a modal, a split pane, etc.). -->
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden w-full h-full flex flex-col">
    <!-- Header & Upload -->
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex justify-between items-center shrink-0">
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
        >
        <button
          @click="triggerFileInput"
          :disabled="isUploading"
          class="px-3 py-1 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 disabled:cursor-not-allowed text-white rounded font-semibold transition-colors text-sm flex items-center"
        >
          <span v-if="isUploading" class="mr-2">⏳</span>
          Upload File
        </button>
      </div>
    </div>

    <!-- File List: ``flex-1`` + ``min-h-0`` so the table expands to fill
         the remaining vertical space without overflowing the panel. -->
    <div class="p-0 flex-1 min-h-0 overflow-y-auto">
      <table class="w-full text-left border-collapse">
        <thead>
          <tr class="bg-gray-900/50 text-gray-400 text-xs uppercase tracking-wider">
            <th class="px-4 py-2 font-medium">Filename</th>
            <th class="px-4 py-2 font-medium w-24">Size</th>
            <th class="px-4 py-2 font-medium w-48 text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="files.length === 0">
            <td colspan="3" class="px-4 py-6 text-center text-gray-500 text-sm">
              No G-code files found. Upload one to get started.
            </td>
          </tr>
          <tr
            v-for="file in files"
            :key="file.filename"
            class="border-t border-gray-700/50 hover:bg-gray-700/30 transition-colors"
          >
            <td class="px-4 py-2 text-sm text-gray-300 font-mono truncate max-w-[200px]" :title="file.filename">
              {{ file.filename }}
            </td>
            <td class="px-4 py-2 text-xs text-gray-400">
              {{ formatSize(file.size_bytes) }}
            </td>
            <td class="px-4 py-2 text-right space-x-2">
              <button
                @click="editFile(file.filename)"
                class="px-2 py-1 bg-purple-600 hover:bg-purple-500 text-white rounded text-xs transition-colors"
              >
                Edit
              </button>
              <button
                @click="loadFile(file.filename)"
                class="px-2 py-1 bg-green-600 hover:bg-green-500 text-white rounded text-xs transition-colors"
              >
                Load
              </button>
              <button
                @click="deleteFile(file.filename)"
                class="px-2 py-1 bg-red-600 hover:bg-red-500 text-white rounded text-xs transition-colors"
              >
                Delete
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
