<script setup>
import { computed, ref, onMounted } from 'vue'
import { Codemirror } from 'vue-codemirror'
import { ini } from '@codemirror/lang-ini'
import { oneDark } from '@codemirror/theme-one-dark'
import { ConfigurationService } from '../../generated/api/services/ConfigurationService'
import { useConsoleStore } from '../stores/console'

const props = defineProps({
  filename: { type: String, required: true },
  modelValue: { type: String, default: '' },
  readOnly: { type: Boolean, default: false },
  mode: { type: String, default: 'config' }
})

// Added the 'save' event
const emit = defineEmits(['update:modelValue', 'close', 'save'])

const consoleStore = useConsoleStore()
const fileContent = ref('')
const isSaving = ref(false)
const isLoaded = ref(false)
const editorExtensions = [ini(), oneDark]

const loadFile = async () => {
  try {
    // If the parent passed content directly (e.g., for a profile), USE IT!
    if (props.mode === 'profile') {
      fileContent.value = props.modelValue || ''
      isLoaded.value = true
      return
    }

    // Legacy fallback: Fetch directly for standard configs
    const res = await ConfigurationService.readConfig(props.filename)
    fileContent.value = res.content || ''
    isLoaded.value = true
  } catch (e) {
    consoleStore.error(`Failed to open ${props.filename}: ${e.message}`)
    alert(`Failed to load file: ${e.message}`)
  }
}

const saveCurrentFile = async () => {
  if (props.readOnly) return

  isSaving.value = true
  try {
    if (props.mode === 'profile') {
      // Delegate saving to the parent component
      emit('save', fileContent.value)
      consoleStore.info(`Saved profile ${props.filename}`)
    } else {
      // Legacy fallback: Save directly for standard configs
      await ConfigurationService.saveConfig(props.filename, { content: fileContent.value })
      consoleStore.info(`Saved config ${props.filename}`)
    }
  } catch(e) {
    consoleStore.error(`Failed to save ${props.filename}: ${e.message}`)
    alert(`Failed to save file: ${e.message}`)
  } finally {
    isSaving.value = false
  }
}

const closeEditor = () => {
  emit('close')
}



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



    <!-- The CodeMirror Editor Area -->
    <div class="flex-1 p-0 relative editor-shell" v-if="isLoaded">
      <Codemirror
        :model-value="fileContent"
        @update:model-value="handleEditorUpdate"
        :extensions="editorExtensions"
        :disabled="!readOnly"
        class="editor-codemirror"
      />
    </div>

    <!-- Loading State -->
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