<script setup>
import { onMounted, ref } from 'vue'
import { CompilerService } from '../services/api/services/CompilerService'
import { useConsoleStore } from '../stores/console'
import ConfigEditor from './ConfigEditor.vue'

const consoleStore = useConsoleStore()

const profiles = ref([])
const selectedProfile = ref('')
const generatedFiles = ref({ source_cfg: '', ini: '', hal: '', json: '' })
const isGenerating = ref(false)
const isDeploying = ref(false)
const viewModalOpen = ref(false)
const viewModalTitle = ref('')
const viewModalContent = ref('')

const fileCards = [
  {
    key: 'source_cfg',
    filename: 'machine.cfg',
    description: '# source for HAL, INI, Remora.json for LinuxCNC',
    modalTitle: 'Staged Source (machine.cfg snapshot)',
  },
  {
    key: 'hal',
    filename: 'machine.hal',
    description: '# Generated HAL for LinuxCNC',
    modalTitle: 'machine.hal',
  },
  {
    key: 'ini',
    filename: 'linuxcnc.ini',
    description: '# Generated INI for LinuxCNC',
    modalTitle: 'linuxcnc.ini',
  },
  {
    key: 'json',
    filename: 'remora.json',
    description: '# Generated Remora JSON payload',
    modalTitle: 'remora.json',
  },
]

const hasGeneratedFiles = () => {
  return Boolean(generatedFiles.value.ini || generatedFiles.value.hal || generatedFiles.value.json)
}

const openViewModal = (title, content) => {
  viewModalTitle.value = title
  viewModalContent.value = content || ''
  viewModalOpen.value = true
}

const closeViewModal = () => {
  viewModalOpen.value = false
  viewModalTitle.value = ''
  viewModalContent.value = ''
}

const loadProfiles = async () => {
  try {
    const response = await CompilerService.listCompilerProfiles()
    profiles.value = Array.isArray(response.profiles) ? response.profiles : []
    if (!selectedProfile.value && profiles.value.length > 0) {
      selectedProfile.value = profiles.value[0]
    }
  } catch (error) {
    consoleStore.addMessage(`Failed to fetch compiler profiles: ${error.message}`, 'error')
  }
}

const generateFiles = async (filename) => {
  if (!selectedProfile.value) {
    consoleStore.addMessage('Please select a profile first.', 'warning')
    return
  }

  isGenerating.value = true
  try {
    const response = await CompilerService.generateCompilerArtifacts(filename)
    const previews = response.generated_files || {}
    generatedFiles.value = {
      source_cfg: '',
      ini: previews.ini || '',
      hal: previews.hal || '',
      json: previews.json || '',
    }
    consoleStore.addMessage(response.message || `Generated staged files for ${selectedProfile.value}`, 'success')
  } catch (error) {
    consoleStore.addMessage(`Generation Failed: ${error.message}`, 'error')
  } finally {
    isGenerating.value = false
  }
}

const deploy = async () => {
  if (!hasGeneratedFiles()) {
    return
  }

  isDeploying.value = true
  try {
    const response = await CompilerService.deployCompilerArtifacts()
    consoleStore.addMessage(response.message || 'Deploy complete. Restart LinuxCNC backend.', 'success')
    if (response.restart_required) {
      consoleStore.addMessage('LinuxCNC restart is required to activate the new configuration.', 'warning')
    }
  } catch (error) {
    consoleStore.addMessage(`Deploy failed: ${error.message}`, 'error')
  } finally {
    isDeploying.value = false
  }
}

onMounted(() => {
  loadProfiles()
})
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden mt-6">
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">Configuration Compiler</h2>
    </div>

    <div class="p-4 space-y-4">
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
        <div class="md:col-span-2">
          <label class="block text-xs uppercase tracking-wider text-gray-400 mb-1">Profile</label>
          <select
            v-model="selectedProfile"
            class="w-full rounded bg-gray-900 border border-gray-600 text-gray-200 px-3 py-2"
          >
            <option disabled value="">Select profile...</option>
            <option v-for="profile in profiles" :key="profile" :value="profile">{{ profile }}</option>
          </select>
        </div>
        <button
          @click="generateFiles(selectedProfile)"
          :disabled="isGenerating || !selectedProfile"
          class="w-full px-3 py-2 rounded font-semibold bg-blue-600 hover:bg-blue-500 disabled:bg-blue-900 disabled:cursor-not-allowed"
        >
          {{ isGenerating ? 'Generating...' : 'Stage & Generate' }}
        </button>
      </div>

      <div v-if="hasGeneratedFiles()" class="space-y-3">
        <div
          v-for="file in fileCards"
          :key="file.key"
          class="flex items-center justify-between gap-4 rounded-lg border border-gray-700 bg-gray-800 p-3 mb-3"
        >
          <div class="min-w-0">
            <div class="font-mono text-sm font-semibold text-gray-100 truncate">{{ file.filename }}</div>
            <div class="text-xs text-gray-400 truncate">{{ file.description }}</div>
          </div>
          <button
            @click="openViewModal(file.modalTitle, generatedFiles[file.key])"
            class="shrink-0 rounded bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-500"
          >
            View
          </button>
        </div>

        <div
          v-if="viewModalOpen"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
        >
          <div class="flex h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-lg border border-gray-700 bg-gray-900 shadow-2xl">
            <div class="flex items-center justify-between border-b border-gray-700 bg-gray-800 px-4 py-3">
              <div>
                <div class="text-xs uppercase tracking-wider text-yellow-300 font-semibold">{{ viewModalTitle }}</div>
              </div>
              <button
                @click="closeViewModal"
                class="rounded bg-gray-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-gray-500"
              >
                Close
              </button>
            </div>
            <div class="flex-1 min-h-0">
              <ConfigEditor v-model="viewModalContent" :readOnly="true" :filename="viewModalTitle" />
            </div>
          </div>
        </div>

        <div class="rounded border-2 border-yellow-500 bg-yellow-100/10 p-3 text-yellow-200 text-sm font-semibold">
          ⚠️ Files Staged! Please flash your Remora board with the generated JSON payload before making this configuration active.
        </div>
      </div>

      <div class="pt-2 border-t border-gray-700">
        <button
          @click="deploy"
          :disabled="isDeploying || !hasGeneratedFiles()"
          class="w-full md:w-auto px-4 py-2 rounded font-semibold bg-red-600 hover:bg-red-500 disabled:bg-red-900 disabled:cursor-not-allowed"
        >
          {{ isDeploying ? 'Deploying...' : 'Confirm Flashed & Deploy' }}
        </button>
        <p class="text-xs text-gray-400 mt-2">After deploy, restart the LinuxCNC backend to apply the active configuration.</p>
      </div>
    </div>
  </div>
</template>
