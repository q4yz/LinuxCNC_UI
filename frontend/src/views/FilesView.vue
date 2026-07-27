<script setup>
// FilesView is now a dedicated full-page view that hosts FileManager.
// ``FileManager`` emits ``edit`` events for each row; we forward them
// to the parent (``App.vue``) so it can mount the shared full-screen
// ``ConfigEditor``. Keeping this forwarding step in the view (rather
// than having FileManager import the editor directly) preserves the
// "view owns layout, component owns display" boundary.
import FileManager from '../components/FileManager.vue';

const emit = defineEmits(['edit']);

function handleEdit(filename) {
  emit('edit', filename);
}
</script>

<template>
  <div class="h-full w-full flex flex-col">
    <FileManager @edit="handleEdit" />
  </div>
</template>
