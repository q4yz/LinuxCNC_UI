<script setup>
import { onMounted, onUnmounted } from "vue";

const props = defineProps({
  title: { type: String, default: "Confirm" },
  question: { type: String, default: "Are you sure?" },
  description: { type: String, default: "" },
  confirmButtonText: { type: String, default: "Confirm" },
  rejectButtonText: { type: String, default: "Cancel" },
  confirmButtonStyle: { type: String, default: "primary" },
  rejectButtonStyle: { type: String, default: "secondary" },
  showDismissCrossButton: { type: Boolean, default: true },
});

const emit = defineEmits(["confirm", "reject"]);

function reject() {
  emit("reject");
}

function onKeydown(event) {
  if (event.key === "Escape") reject();
}

onMounted(() => window.addEventListener("keydown", onKeydown));
onUnmounted(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" @click.self="reject">
    <section class="w-full max-w-md rounded-lg border border-gray-700 bg-gray-900 p-6 text-white shadow-2xl" role="dialog" aria-modal="true">
      <div class="flex items-start justify-between gap-4">
        <h2 class="text-lg font-semibold text-gray-100">{{ props.title }}</h2>
        <button v-if="props.showDismissCrossButton" type="button" class="text-xl text-gray-400 hover:text-white" aria-label="Close" @click="reject">×</button>
      </div>
      <p class="mt-4 text-gray-200">{{ props.question }}</p>
      <p v-if="props.description" class="mt-2 text-sm text-gray-400">{{ props.description }}</p>
      <div class="mt-6 flex justify-end gap-3">
        <button type="button" class="rounded border border-gray-600 px-4 py-2 text-sm font-semibold text-gray-200 hover:bg-gray-800" @click="reject">{{ props.rejectButtonText }}</button>
        <button type="button" class="rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500" @click="emit('confirm')">{{ props.confirmButtonText }}</button>
      </div>
    </section>
  </div>
</template>
