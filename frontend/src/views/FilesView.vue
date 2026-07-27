<script setup>
// FilesView is a dedicated full-page view that hosts ``FileManager``.
// ``FileManager`` emits ``edit`` events for each row with the
// arguments ``(filename, readOnly, mode, content)`` (Issue #60); we
// forward them as-is to the parent (``App.vue``) so the full-screen
// ``ConfigEditor`` receives the same mode tag the widget set.
//
// Keeping this forwarding step in the view (rather than having
// FileManager import the editor directly) preserves the "view owns
// layout, component owns display" boundary and means the file list
// can be reused inside a different layout without rewiring the emit.
import FileManager from '../components/FileManager.vue';

const emit = defineEmits(['edit']);

// ``...args`` keeps the four-argument signature of the inner emit so
// ``mode="profile"`` survives the trip up to App.vue.
function handleEdit(...args) {
  emit('edit', ...args);
}
</script>

<template>
  <div class="h-full w-full flex flex-col">
    <FileManager @edit="handleEdit" />
  </div>
</template>
