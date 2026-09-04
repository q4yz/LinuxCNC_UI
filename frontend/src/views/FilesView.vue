<script setup lang="ts">
// Dedicated full-page view that hosts ``FileManager``. ``edit``
// events are forwarded as-is to the parent (``App.vue``) so the
// full-screen ``ConfigEditor`` receives the same mode tag. Keeping
// the forwarding in the view (not in ``FileManager``) preserves
// the layout-vs-display boundary and lets the file list be reused
// in other layouts.
import FileManager from '../components/FileManager.vue';
import ActivePrintWidget from "../components/ActivePrintWidget.vue";
import MachineGate from "../components/machine/MachineGate.vue";

const emit = defineEmits(['edit']);

// ``...args`` keeps the four-argument inner-emit signature so
// ``mode="profile"`` survives the trip up to App.vue.
function handleEdit(...args: unknown[]) {
  emit('edit', ...args);
}
</script>

<template>
  <div class="h-full w-full flex flex-col">
    <FileManager @edit="handleEdit" class="mb-4" />
    <MachineGate label="Job status">
      <ActivePrintWidget />
    </MachineGate>
  </div>
</template>
