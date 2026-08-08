<script setup>
import { ref, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useMachineStore } from '../stores/machine-compat'
import { useConsoleStore } from '../stores/console'
import { SystemService } from '../../generated/api/services/SystemService'

const store = useMachineStore()
const consoleStore = useConsoleStore()
const { isUpdating } = storeToRefs(store)

const currentVersion = ref('loading...')
const latestVersion = ref('unknown')

const fetchVersion = async () => {
  try {
    const res = await SystemService.getVersionInfo()
    // Prefer the simple `version` field (commit hash) if present
    currentVersion.value = res.version || res.current_version || 'unknown'
    latestVersion.value = res.latest_version || res.version || 'unknown'
    if (res.update_available) {
      consoleStore.info('Update available')
    }
  } catch (error) {
    consoleStore.error(`Failed to fetch version: ${error.message}`)
    currentVersion.value = 'error'
  }
}

const updateSystem = async () => {
  if (!confirm("Are you sure you want to update the system? The machine will stop and connection may be lost.")) {
    return
  }

  try {
    store.$patch({ isUpdating: true })
    consoleStore.warning("System update initiated. Connection may be lost temporarily...")
    await SystemService.triggerSystemUpdate()

    // We expect the websocket to drop or page to reload eventually,
    // but we can optionally reload after a timeout.
    setTimeout(() => {
      window.location.reload()
    }, 10000)
  } catch (error) {
    store.$patch({ isUpdating: false })
    consoleStore.error(`Update failed to start: ${error.message}`)
  }
}

onMounted(() => {
  fetchVersion()
})
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden mt-6">
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex justify-between items-center">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        <span class="mr-2">⚙️</span> System Update
      </h2>
    </div>
    
    <div class="p-4 flex items-center justify-between">
      <div class="flex flex-col">
        <span class="text-gray-400 text-xs">Current Version</span>
        <span class="font-mono text-lg font-bold text-gray-200">{{ currentVersion }}</span>
        <span class="text-gray-400 text-xs">Latest</span>
        <span class="font-mono text-sm text-gray-400">{{ latestVersion }}</span>
      </div>
      
      <button 
        @click="updateSystem"
        class="px-4 py-2 bg-yellow-600 hover:bg-yellow-500 text-white rounded font-semibold transition-colors flex items-center shadow"
      >
        <span class="mr-2">🔄</span> Update System
      </button>
    </div>

    <!-- Fullscreen Overlay using Teleport -->
    <Teleport to="body">
      <div 
        v-if="isUpdating" 
        class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/90 backdrop-blur-sm"
      >
        <div class="flex flex-col items-center p-8 bg-gray-800 border border-gray-700 rounded-xl shadow-2xl max-w-md w-full text-center">
          <div class="w-16 h-16 mb-6 border-4 border-yellow-500 border-t-transparent rounded-full animate-spin"></div>
          <h2 class="text-2xl font-bold text-white mb-2 tracking-wide">UPDATING SYSTEM</h2>
          <p class="text-gray-400">Please wait while the system pulls the latest updates and reinstalls dependencies. The page will reload automatically.</p>
        </div>
      </div>
    </Teleport>
  </div>
</template>
