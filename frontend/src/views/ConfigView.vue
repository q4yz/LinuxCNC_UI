<script setup>
// Placeholder for Config View
import ConfigList from '../components/ConfigList.vue';
import DebugPanel from '../components/DebugPanel.vue';
</script>

<template>
  <div class="h-full bg-gray-800 rounded-lg border border-gray-700 shadow-xl p-6 flex flex-col items-center justify-center">
    
    <div class="lg:col-span-1 flex flex-col space-y-6">
      <ConfigList />
      
      <div class="shrink-0 h-64">
         <DebugPanel />
      </div>
      

    </div>


    

    

<!-- Debug Panel (Throttled Raw State) -->
        

  </div>
</template>
