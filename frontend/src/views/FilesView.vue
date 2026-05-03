<script setup>
import FileManager from '../components/FileManager.vue';

// Placeholder for Files View
</script>

<template>
  <div class="h-full bg-gray-800 rounded-lg border border-gray-700 shadow-xl p-6 flex flex-col items-center justify-center">
    <div class="text-gray-500 mb-4">
      <svg class="w-16 h-16 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
      <h2 class="text-xl font-bold uppercase tracking-widest text-center">G-Code File Manager</h2>

      <FileManager />

    </div>
    <p class="text-sm">This component has not been implemented yet.</p>
  </div>
</template>
