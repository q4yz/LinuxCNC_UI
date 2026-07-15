<script setup>
import { computed, ref, onMounted } from 'vue'
import { Codemirror } from 'vue-codemirror'
import { ini } from '@codemirror/lang-ini'
import { oneDark } from '@codemirror/theme-one-dark'
import { ConfigurationService } from '../services/api/services/ConfigurationService'
import { useConsoleStore } from '../stores/console'

const props = defineProps({
  filename: {
    type: String,
    required: true
  },
  modelValue: {
    type: String,
    default: ''
  },
  readOnly: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:modelValue'])

const consoleStore = useConsoleStore()
const fileContent = ref('')
const isSaving = ref(false)
const isLoaded = ref(false)
const editorExtensions = [ini(), oneDark]
const previewStorageKey = computed(() => `config-editor-preview:${props.filename}`)

const loadFile = async () => {
  try {
    if (props.readOnly && props.modelValue) {
      fileContent.value = props.modelValue
      isLoaded.value = true
      return
    }

    if (props.readOnly) {
      const previewContent = window.localStorage.getItem(previewStorageKey.value)
      if (previewContent !== null) {
        fileContent.value = previewContent
        isLoaded.value = true
        return
      }
    }

    const res = await ConfigurationService.readConfig(props.filename)
    fileContent.value = res.content
    isLoaded.value = true
  } catch (e) {
    consoleStore.addMessage(`Failed to open ${props.filename}: ${e.message}`, 'error')
    alert(`Failed to load file: ${e.message}`)
  }
}

const saveCurrentFile = async () => {
  if (props.readOnly) {
    return
  }

  isSaving.value = true
  try {
    await ConfigurationService.saveConfig(props.filename, { content: fileContent.value })
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

const editorTitle = computed(() => (props.readOnly ? 'Viewing:' : 'Editing:'))
const editorIcon = computed(() => (props.readOnly ? '👁️' : '✏️'))

const handleEditorUpdate = (value) => {
  fileContent.value = value
  emit('update:modelValue', value)
}

onMounted(() => {
  loadFile()
})
</script>

<template>
  <div class="min-h-screen w-full flex flex-col bg-gray-900 text-gray-200">
    <div class="bg-gray-800 px-6 py-4 border-b border-gray-700 flex justify-between items-center shrink-0 shadow-md">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        <span class="mr-2">{{ editorIcon }}</span> {{ editorTitle }} <span class="ml-2 text-blue-400 font-mono lowercase text-base">{{ filename }}</span>
      </h2>
      <div class="space-x-3">
        <button
          @click="closeEditor"
          class="px-4 py-2 bg-gray-600 hover:bg-gray-500 text-white rounded font-semibold transition-colors text-sm"
        >
          Close Editor
        </button>
        <button
          v-if="!readOnly"
          @click="saveCurrentFile"
          :disabled="isSaving || !isLoaded"
          class="px-4 py-2 bg-green-600 hover:bg-green-500 disabled:bg-green-800 disabled:cursor-not-allowed text-white rounded font-semibold transition-colors text-sm shadow"
        >
          {{ isSaving ? 'Saving...' : 'Save File' }}
        </button>
      </div>
    </div>
    
    <div class="flex-1 p-0 relative editor-shell" v-if="isLoaded">
      <Codemirror
        :model-value="fileContent"
        @update:model-value="handleEditorUpdate"
        :extensions="editorExtensions"
        :disabled="readOnly"
        class="editor-codemirror"
      />
    </div>
    <div v-else class="flex-1 flex items-center justify-center">
      <div class="text-gray-500 text-lg flex items-center">
        <div class="w-6 h-6 mr-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
        Loading...
      </div>
    </div>
  </div>
</template>

<style scoped>
.editor-shell {
  min-height: 0;
}

.editor-codemirror {
  height: 100%;
  width: 100%;
}

:deep(.cm-editor) {
  height: 100%;
  width: 100%;
  outline: none;
  background: rgb(17 24 39);
}

:deep(.cm-scroller) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
}
</style>
