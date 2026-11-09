<script setup lang="ts">
// The bin that appears while an explorer entry is dragged: drop on it to
// delete (the explorer asks for confirmation as it does from the ⋮ menu).
import Icon from "./Icon.vue";

defineProps<{ visible: boolean; active: boolean }>();
const emit = defineEmits<{
  (e: "over", event: DragEvent): void;
  (e: "leave"): void;
  (e: "drop", event: DragEvent): void;
}>();
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-from-class="translate-y-6 opacity-0"
      leave-to-class="translate-y-6 opacity-0"
      enter-active-class="transition duration-150"
      leave-active-class="transition duration-150"
    >
      <div
        v-if="visible"
        class="fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-full border-2 px-6 py-3 text-sm font-semibold"
        :class="active ? 'border-red-400 bg-red-600 text-white scale-110' : 'border-red-500/60 bg-gray-900/95 text-red-300'"
        data-test="drag-bin"
        @dragover="emit('over', $event)"
        @dragleave="emit('leave')"
        @drop="emit('drop', $event)"
      >
        <Icon name="trash" class="h-6 w-6" /> Drop here to delete
      </div>
    </Transition>
  </Teleport>
</template>
