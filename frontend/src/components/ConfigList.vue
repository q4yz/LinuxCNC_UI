<script setup>
import { ref, onMounted } from 'vue'
import { ConfigurationService } from '../../generated/api/services/ConfigurationService'
import { ProgramExecutionService } from '../../generated/api/services/ProgramExecutionService'
import { useConsoleStore } from '../stores/console'

const consoleStore = useConsoleStore()
const configs = ref([])

const loadConfigs = async () => {
  try {
    configs.value = await ConfigurationService.listConfigs()
  } catch (e) {
    consoleStore.addMessage(`Failed to fetch configs: ${e.message}`, 'error')
  }
}

const parseKlipper = async () => {
  try {
    consoleStore.addMessage("Triggering Klipper-to-LinuxCNC parser...", 'command')
    await ProgramExecutionService.triggerParser()
    consoleStore.addMessage("Parsing started in background.", 'info')
  } catch (e) {
    consoleStore.addMessage(`Parser failed: ${e.message}`, 'error')
  }
}

const openEditor = (filename) => {
  window.open(window.location.origin + '/?editor=' + encodeURIComponent(filename), '_blank')
}

const formatSize = (bytes) => {
  if (bytes < 1024) return bytes + ' B'
  else if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB'
  else return (bytes / 1048576).toFixed(1) + ' MB'
}

onMounted(() => {
  loadConfigs()
})
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden mt-6 flex flex-col min-h-[300px]">
    <div class="flex flex-col h-full">
      <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex justify-between items-center">
        <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
          <span class="mr-2">📝</span> Configuration Files
        </h2>
        <button
          @click="parseKlipper"
          class="px-3 py-1 bg-purple-600 hover:bg-purple-500 text-white rounded font-semibold transition-colors text-sm flex items-center shadow"
        >
          <span class="mr-2">🔄</span> Parse to LinuxCNC
        </button>
      </div>

      <div class="p-0 overflow-y-auto max-h-64 flex-1">
        <table class="w-full text-left border-collapse">
          <thead>
            <tr class="bg-gray-900/50 text-gray-400 text-xs uppercase tracking-wider">
              <th class="px-4 py-2 font-medium">Filename</th>
              <th class="px-4 py-2 font-medium w-24">Size</th>
              <th class="px-4 py-2 font-medium w-24 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="configs.length === 0">
              <td colspan="3" class="px-4 py-6 text-center text-gray-500 text-sm">
                No config files found in machine_config/.
              </td>
            </tr>
            <tr
              v-for="file in configs"
              :key="file.filename"
              class="border-t border-gray-700/50 hover:bg-gray-700/30 transition-colors"
            >
              <td class="px-4 py-2 text-sm text-gray-300 font-mono truncate">{{ file.filename }}</td>
              <td class="px-4 py-2 text-xs text-gray-400">{{ formatSize(file.size_bytes) }}</td>
              <td class="px-4 py-2 text-right">
                <button
                  @click="openEditor(file.filename)"
                  class="px-2 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs transition-colors"
                >
                  Edit
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
