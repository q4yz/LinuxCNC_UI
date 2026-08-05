<script setup>
// Toolbar with the Save / Run / Delete / New buttons for the
// macro editor. All actions emit events; the parent owns the
// actual store calls so the toolbar stays a pure presentational
// component.

defineProps({
  activeName: { type: String, default: '' },
  dirty: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  running: { type: Boolean, default: false },
});

const emit = defineEmits(['save', 'run', 'delete', 'new']);
</script>

<template>
  <div class="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
    <div class="flex items-center gap-2">
      <span class="text-xs uppercase tracking-wider text-gray-400">Macro Editor</span>
      <span v-if="activeName" class="font-mono text-sm text-blue-300">
        {{ activeName }}
        <span v-if="dirty" class="ml-1 inline-block w-2 h-2 rounded-full bg-yellow-400 align-middle" title="Unsaved changes"></span>
      </span>
    </div>

    <div class="flex items-center gap-2">
      <button
        type="button"
        class="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded font-semibold disabled:opacity-50"
        :disabled="!activeName || !dirty || saving"
        @click="emit('save')"
      >
        Save
      </button>
      <button
        type="button"
        class="px-3 py-1 text-sm bg-green-600 hover:bg-green-500 text-white rounded font-semibold disabled:opacity-50"
        :disabled="!activeName || running"
        @click="emit('run')"
      >
        Run
      </button>
      <button
        type="button"
        class="px-3 py-1 text-sm bg-red-600 hover:bg-red-500 text-white rounded font-semibold disabled:opacity-50"
        :disabled="!activeName || running"
        @click="emit('delete')"
      >
        Delete
      </button>
      <button
        type="button"
        class="px-3 py-1 text-sm bg-gray-600 hover:bg-gray-500 text-white rounded font-semibold"
        @click="emit('new')"
      >
        New
      </button>
    </div>
  </div>
</template>
