<script setup>
// Placeholder for Config View
import ConfigList from '../components/ConfigList.vue';
import DebugPanel from '../components/DebugPanel.vue';
import UpdateManager from '../components/UpdateManager.vue';
import CompilerPanel from '../components/CompilerPanel.vue';
</script>

<template>
  
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 pb-8">
      <div class="col-span-1 flex flex-col space-y-6">
          <UpdateManager />
          <ConfigList />
          <CompilerPanel />
      </div>
      <div class="flex flex-col space-y-6">
        <div class="shrink-0 h-256">
            <DebugPanel />
        </div>
      </div>
      

      
  

<!-- Debug Panel (Throttled Raw State) -->
        

  </div>
</template>
