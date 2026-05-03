<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../services/api'
import { useConsoleStore } from '../stores/console'

const props = defineProps({
  filename: {
    type: String,
    required: true
  }
})

const consoleStore = useConsoleStore()
const fileContent = ref('')
const isSaving = ref(false)
const isLoaded = ref(false)

const loadFile = async () => {
  try {
    const res = await api.readConfig(props.filename)
    fileContent.value = res.content
    isLoaded.value = true
  } catch (e) {
    consoleStore.addMessage(`Failed to open ${props.filename}: ${e.message}`, 'error')
    alert(`Failed to load file: ${e.message}`)
  }
}

const saveCurrentFile = async () => {
  isSaving.value = true
  try {
    await api.saveConfig(props.filename, fileContent.value)
    consoleStore.addMessage(`Saved config ${props.filename}`, 'success')
  } catch (e) {
    consoleStore.addMessage(`Failed to save ${props.filename}: ${e.message}`, 'error')
    alert(`Failed to save file: ${e.message}`)
  } finally {
    isSaving.value = false
  }
}

const closeEditor = () => {
  window.close()
}

onMounted(() => {
  loadFile()
})
</script>

<template>
  <div class="min-h-screen w-full flex flex-col bg-gray-900 text-gray-200">
    <div class="bg-gray-800 px-6 py-4 border-b border-gray-700 flex justify-between items-center shrink-0 shadow-md">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        <span class="mr-2">✏️</span> Editing: <span class="ml-2 text-blue-400 font-mono lowercase text-base">{{ filename }}</span>
      </h2>
      <div class="space-x-3">
        <button
          @click="closeEditor"
          class="px-4 py-2 bg-gray-600 hover:bg-gray-500 text-white rounded font-semibold transition-colors text-sm"
        >
          Close Editor
        </button>
        <button
          @click="saveCurrentFile"
          :disabled="isSaving || !isLoaded"
          class="px-4 py-2 bg-green-600 hover:bg-green-500 disabled:bg-green-800 disabled:cursor-not-allowed text-white rounded font-semibold transition-colors text-sm shadow"
        >
          {{ isSaving ? 'Saving...' : 'Save File' }}
        </button>
      </div>
    </div>
    
    <div class="flex-1 p-0 relative" v-if="isLoaded">
      <textarea
        v-model="fileContent"
        class="absolute inset-0 w-full h-full p-6 bg-gray-900 text-gray-200 font-mono text-sm resize-none focus:outline-none"
        spellcheck="false"
      ></textarea>
    </div>
    <div v-else class="flex-1 flex items-center justify-center">
      <div class="text-gray-500 text-lg flex items-center">
        <div class="w-6 h-6 mr-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
        Loading...
      </div>
    </div>
  </div>
</template>
