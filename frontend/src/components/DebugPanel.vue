<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useMachineStore } from '../stores/machine'

const store = useMachineStore()
const throttledState = ref({})
let intervalId = null

onMounted(() => {
  // Take an initial snapshot immediately
  throttledState.value = JSON.parse(JSON.stringify(store.$state))
  
  // Update snapshot every 3000ms
  intervalId = setInterval(() => {
    throttledState.value = JSON.parse(JSON.stringify(store.$state))
  }, 3000)
})

onUnmounted(() => {
  if (intervalId) {
    clearInterval(intervalId)
  }
})
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden flex flex-col h-full">
    <!-- Header -->
    <div class="bg-gray-700/50 px-4 py-2 border-b border-gray-600 flex justify-between items-center">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">Raw Machine State (3s Snapshot)</h2>
    </div>
    
    <!-- Code Area -->
    <div class="flex-1 p-4 bg-gray-900 overflow-y-auto">
      <pre><code class="text-xs text-green-400 font-mono">{{ JSON.stringify(throttledState, null, 2) }}</code></pre>
    </div>
  </div>
</template>
