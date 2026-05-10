<script setup>
import { ref, computed } from 'vue'

const hasError = ref(false)

// Dynamically grabs the stream through the Vite proxy or relative production path.
// We append a timestamp cache-buster so the browser re-fetches if the connection drops.
const streamUrl = computed(() => {
  return `/api/v1/camera/stream?t=${new Date().getTime()}`
})

const handleError = () => {
  hasError.value = true
}

const retryCamera = () => {
  hasError.value = false
}
</script>

<template>
  <div class="camera-panel w-full h-full min-h-[300px] bg-gray-900 rounded-lg overflow-hidden relative flex items-center justify-center border border-gray-700">
    
    <!-- Loading / Fallback UI -->
    <div v-if="hasError" class="absolute flex flex-col items-center justify-center text-gray-400 z-10">
      <svg xmlns="http://www.w3.org/2000/svg" class="h-12 w-12 mb-2 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
      </svg>
      <span class="text-sm font-semibold">Camera Offline</span>
      <button @click="retryCamera" class="mt-4 px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs transition-colors cursor-pointer text-white">
        Retry Connection
      </button>
    </div>

    <!-- Native MJPEG HTML Stream -->
    <img 
      v-if="!hasError"
      :src="streamUrl" 
      @error="handleError"
      alt="Live Webcam" 
      class="w-full h-full object-cover"
    />
    
    <!-- Overlay Label -->
    <div class="absolute top-4 left-4 pointer-events-none">
      <div class="bg-gray-900/80 backdrop-blur text-xs text-gray-300 px-3 py-1.5 rounded border border-gray-700 shadow font-mono">
        Live Feed
      </div>
    </div>

  </div>
</template>