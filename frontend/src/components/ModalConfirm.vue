<script setup lang="ts">
import { computed, onMounted, onUnmounted } from "vue";
import { BaseButton, Icon } from "../ui/index.ts";

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

// ``ModalButtonStyle`` carries eight legacy tokens; the BaseButton
// library speaks five variants. Map the tokens the modal actually
// receives and degrade everything else to ``secondary``. This map
// also fixes a latent bug: the template used to hard-code the blue
// primary look, so ``danger`` confirms rendered blue.
const STYLE_TO_VARIANT: Record<string, string> = {
  primary: "primary",
  success: "success",
  danger: "danger",
  secondary: "secondary",
};

const confirmVariant = computed(
  () => STYLE_TO_VARIANT[props.confirmButtonStyle] ?? "secondary",
);
const rejectVariant = computed(
  () => STYLE_TO_VARIANT[props.rejectButtonStyle] ?? "secondary",
);

function reject() {
  emit("reject");
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") reject();
}

onMounted(() => window.addEventListener("keydown", onKeydown));
onUnmounted(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" @click.self="reject">
    <section class="w-full max-w-md rounded-lg border border-gray-700 bg-gray-900 p-6 text-white" role="dialog" aria-modal="true">
      <div class="flex items-start justify-between gap-4">
        <h2 class="text-lg font-semibold text-gray-100">{{ props.title }}</h2>
        <BaseButton v-if="props.showDismissCrossButton" variant="ghost" size="sm" aria-label="Close" @click="reject">
          <template #icon><Icon name="close" class="h-4 w-4" /></template>
        </BaseButton>
      </div>
      <p class="mt-4 text-gray-200">{{ props.question }}</p>
      <p v-if="props.description" class="mt-2 text-sm text-gray-400">{{ props.description }}</p>
      <div class="mt-6 flex justify-end gap-3">
        <BaseButton :variant="rejectVariant" @click="reject">{{ props.rejectButtonText }}</BaseButton>
        <BaseButton :variant="confirmVariant" @click="emit('confirm')">{{ props.confirmButtonText }}</BaseButton>
      </div>
    </section>
  </div>
</template>
