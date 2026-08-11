<script setup>
// Shared single-modal confirm primitive.
//
// Two flavours of confirmation live in this codebase:
//
//   1. **Queue-based** — :func:`useConfirm` in ``core/confirm.js``
//      pushes a modal onto a global queue handled by
//      ``ModalConfirmHost.vue``. Use this for inline confirmations
//      tied to a click handler. The queue makes two consecutive
//      confirm dialogs render correctly without one stomping on
//      the other.
//
//   2. **Inline** — this component, used as ``<Confirm v-model:open
//      =…/>`` directly inside a host. Use it for confirmations
//      gated by application state (``showDeleteConfirm = …``) or
//      driven by a watcher.
//
// Both share the same Tailwind palette (gray-900 panel on a
// black/70 backdrop, gray-700 border, danger/primary/secondary
// button pairing) so operators see a single visual language. The
// ``core/confirm.js`` helper's modal renders through this same
// component when wired via :func:`registerModalComponent`, but
// keeps the queue semantics for the common case.
//
// Keyboard support: ``Escape`` closes; ``Enter`` confirms; the
// backdrop click closes by default. ``closeOnBackdrop`` /
// ``closeOnEsc`` opt-out flags match ``Drawer.vue`` so a caller
// can pin the modal open while a destructive operation is in
// flight (the modal stays visible until the caller sets ``open``
// back to ``false``).

import { onBeforeUnmount, onMounted, watch } from "vue";

import Icon from "./Icon.vue";
import Button from "./Button.vue";

const props = defineProps({
  // Two-way bound. Setting to ``false`` from outside emits
  // ``update:open``. The component never sets ``open`` to ``true``
  // itself — that is the caller's job.
  open: { type: Boolean, default: false },
  title: { type: String, default: "Confirm" },
  question: { type: String, default: "Are you sure?" },
  description: { type: String, default: "" },
  // Button labels. The host picks text that fits the operator's
  // mental model ("Delete", "Unload", "Reset") rather than the
  // generic "Confirm" / "Cancel".
  confirmButtonText: { type: String, default: "Confirm" },
  rejectButtonText: { type: String, default: "Cancel" },
  // Button variants — see ``Button.vue``. ``primary`` matches the
  // default confirm action; ``danger`` is for destructive flows
  // (delete, reset). ``secondary`` is reserved for soft prompts
  // where the operator is unlikely to regret the action.
  confirmButtonStyle: {
    type: String,
    default: "primary",
    validator: (v) => ["primary", "success", "danger"].includes(v),
  },
  rejectButtonStyle: {
    type: String,
    default: "secondary",
    validator: (v) => ["primary", "secondary"].includes(v),
  },
  // Closing the modal via backdrop / Escape does **not** fire the
  // ``confirm`` event — it fires ``cancel`` instead. Treat those as
  // distinct paths so the host does not silently perform the
  // destructive action on dismiss.
  closeOnBackdrop: { type: Boolean, default: true },
  closeOnEsc: { type: Boolean, default: true },
  // Whether to show the ``×`` dismiss cross in the header. The
  // ``core/confirm.js`` queue helper uses ``true`` so a long
  // queue can be cancelled mid-flight; consumers wiring this
  // component directly may opt out for dialogs that demand an
  // explicit choice.
  showDismissCrossButton: { type: Boolean, default: true },
});

const emit = defineEmits(["update:open", "confirm", "cancel"]);

function close() {
  emit("update:open", false);
  emit("cancel");
}

function confirm() {
  emit("update:open", false);
  emit("confirm");
}

function onBackdropClick() {
  if (props.closeOnBackdrop) close();
}

function onKeydown(event) {
  if (!props.open) return;
  if (event.key === "Escape" && props.closeOnEsc) close();
  else if (event.key === "Enter" && !event.shiftKey) confirm();
}

onMounted(() => {
  if (typeof window !== "undefined") {
    window.addEventListener("keydown", onKeydown);
  }
});
onBeforeUnmount(() => {
  if (typeof window !== "undefined") {
    window.removeEventListener("keydown", onKeydown);
  }
});

// Lock body scroll while the modal is on screen so the backdrop
// covers the page even when the host content is taller than the
// viewport. The lock is a single boolean — multiple nested
// modals share the lock because a single ``Confirm``-flavoured
// modal is the common case.
watch(
  () => props.open,
  (open) => {
    if (typeof document === "undefined") return;
    document.body.style.overflow = open ? "hidden" : "";
  },
);
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition-opacity duration-150"
      leave-active-class="transition-opacity duration-150"
      enter-from-class="opacity-0"
      leave-to-class="opacity-0"
    >
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
        data-test="confirm-backdrop"
        @click="onBackdropClick"
      >
        <section
          class="w-full max-w-md rounded-lg border border-gray-700 bg-gray-900 p-6 text-white shadow-2xl"
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-title"
          @click.stop
        >
          <header class="flex items-start justify-between gap-4">
            <h2
              id="confirm-title"
              class="text-lg font-semibold text-gray-100"
            >
              {{ title }}
            </h2>
            <button
              v-if="showDismissCrossButton"
              type="button"
              class="text-xl leading-none text-gray-400 hover:text-white"
              aria-label="Close"
              data-test="confirm-dismiss"
              @click="close"
            >
              <Icon name="close" size="h-4 w-4" />
            </button>
          </header>

          <p class="mt-4 text-gray-200">{{ question }}</p>
          <p v-if="description" class="mt-2 text-sm text-gray-400">
            {{ description }}
          </p>

          <footer class="mt-6 flex justify-end gap-3">
            <Button
              :variant="rejectButtonStyle"
              data-test="confirm-reject"
              @click="close"
            >
              {{ rejectButtonText }}
            </Button>
            <Button
              :variant="confirmButtonStyle"
              data-test="confirm-accept"
              @click="confirm"
            >
              {{ confirmButtonText }}
            </Button>
          </footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>
