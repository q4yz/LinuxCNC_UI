<script setup>
import { onMounted } from 'vue'
import { useMachineStore } from './stores/machine'
import DroPanel from './components/DroPanel.vue'
import JogControls from './components/JogControls.vue'
import GCodeViewer from './components/GCodeViewer.vue'
import ConsolePanel from './components/ConsolePanel.vue'

const store = useMachineStore()

onMounted(() => {
  store.connect()
})
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-gray-200 flex flex-col md:flex-row font-sans">
    
    <!-- Sidebar Navigation -->
    <aside class="w-full md:w-64 bg-gray-800 border-r border-gray-700 flex flex-col">
      <div class="p-6 border-b border-gray-700 flex items-center justify-between">
        <h1 class="text-xl font-bold tracking-wider text-blue-400">LinuxCNC Web</h1>
        
        <!-- Connection Status Indicator -->
        <div class="flex items-center space-x-2">
          <span 
            class="h-3 w-3 rounded-full"
            :class="{
              'bg-green-500': store.connectionStatus === 'connected',
              'bg-yellow-500 animate-pulse': store.connectionStatus === 'connecting',
              'bg-red-500': store.connectionStatus === 'disconnected'
            }"
          ></span>
        </div>
      </div>
      
      <nav class="flex-1 p-4 space-y-2">
        <a href="#" class="block px-4 py-2 rounded bg-gray-700 text-white font-medium">Dashboard</a>
        <a href="#" class="block px-4 py-2 rounded hover:bg-gray-700 transition-colors">G-Code Files</a>
        <a href="#" class="block px-4 py-2 rounded hover:bg-gray-700 transition-colors">Machine Config</a>
      </nav>
    </aside>

    <!-- Main Content Area -->
    <main class="flex-1 p-6 lg:p-8 overflow-y-auto">

      <!-- Grid Layout for Panels -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        <!-- Left Column: DRO & Controls -->
        <div class="col-span-1 flex flex-col">
          <DroPanel />
          <JogControls />
        </div>

        <!-- Right Column: 3D Viewer & Console -->
        <div class="lg:col-span-2 flex flex-col space-y-6">
          
          <!-- 3D Viewer -->
          <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl min-h-[400px] overflow-hidden flex flex-col">
            <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600">
              <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">Toolpath</h2>
            </div>
            <div class="flex-1 relative">
              <GCodeViewer />
            </div>
          </div>
          
          <!-- Terminal / Console -->
          <ConsolePanel />

        </div>

      </div>
    </main>
  </div>
</template>
