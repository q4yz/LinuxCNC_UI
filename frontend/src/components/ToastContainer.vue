<script setup>
// ToastContainer — renders the toasts queued by ``useToast()``
// and handles their lifecycle (auto-dismiss timer + manual close).
//
// The component is mounted once at the application root (see
// ``App.vue``) so every module's toast calls land in the same DOM
// subtree. Tailwind utilities drive the colour palette so the
// styling stays consistent with the rest of the dark theme
// (``bg-gray-800`` / ``border-gray-700``).

import { computed, onBeforeUnmount, ref, watch } from "vue";
import {
  TOAST_TYPE_STYLES,
  TOAST_TYPES,
  useToastStore,
} from "../core/toast.js";

const toastStore = useToastStore();

// Active per-toast timers keyed by id. ``Map`` so the cleanup
// hook can iterate deterministically; a plain object would also
// work but loses ordering on insertion / iteration.
const timers = new Map();

function scheduleDismiss(toast) {
  // ``durationMs === null`` means "persist until the operator
  // closes the toast". ``0`` / negative / non-finite are
  // normalised to ``null`` so a malformed call site never causes
  // a flash-and-gone.
  if (!Number.isFinite(toast.durationMs) || toast.durationMs <= 0) {
    return;
  }
  // Clear any previous timer for this id (the queue might have
  // been mutated under us).
  const existing = timers.get(toast.id);
  if (existing) clearTimeout(existing);
  const handle = setTimeout(() => {
    toastStore.dismiss(toast.id);
    timers.delete(toast.id);
  }, toast.durationMs);
  timers.set(toast.id, handle);
}

// Watch the queue and ensure every transient toast has a timer.
// ``deep: true`` is mandatory because the store mutates the array
// in place via ``push`` / ``filter`` — without it, ``watch`` would
// miss the in-place mutation.
watch(
  () => toastStore.toasts,
  (next) => {
    const liveIds = new Set(next.map((t) => t.id));
    // Drop timers for toasts that disappeared without our
    // cooperation (e.g. cleared via ``clear()``).
    for (const id of timers.keys()) {
      if (!liveIds.has(id)) {
        clearTimeout(timers.get(id));
        timers.delete(id);
      }
    }
    // Schedule timers for newly added transient toasts.
    for (const toast of next) {
      if (!timers.has(toast.id)) {
        scheduleDismiss(toast);
      }
    }
  },
  { deep: true, immediate: true },
);

// Clean up every outstanding timer when the container itself
// unmounts (e.g. Vite HMR or a future lazy-routing experiment).
onBeforeUnmount(() => {
  for (const handle of timers.values()) clearTimeout(handle);
  timers.clear();
});

const visibleToasts = computed(() =>
  toastStore.toasts.filter((toast) => TOAST_TYPES.includes(toast.type)),
);

function styleFor(type) {
  // ``TOAST_TYPE_STYLES`` always carries an entry for every type,
  // but a future rename should not silently drop the border. Fall
  // back to the ``info`` palette so the toast stays visible.
  return TOAST_TYPE_STYLES[type] || TOAST_TYPE_STYLES.info;
}

function onClose(id) {
  toastStore.dismiss(id);
}

// Track the first render so a hard-coded "0" id is impossible even
// in the rare case the test harness races the Date.now() clock.
const _renderEpoch = ref(Date.now());
</script>

<template>
  <!--
    Fixed-position container anchored to the bottom-right. ``z-50``
    puts the layer above the rest of the app so a deep-down
    panel cannot accidentally cover a popup. ``pointer-events-none``
    on the outer wrapper lets clicks pass through the empty
    regions; each toast re-enables pointer events on itself.
  -->
  <div
    class="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-80 max-w-[90vw] pointer-events-none"
    data-test="toast-container"
    :data-render-epoch="_renderEpoch"
  >
    <div
      v-for="toast in visibleToasts"
      :key="toast.id"
      :class="[
        'bg-gray-800 text-gray-100 rounded-md border border-gray-700 shadow-xl px-3 py-2 pointer-events-auto flex items-start gap-2',
        styleFor(toast.type).borderClass,
      ]"
      role="status"
      :aria-live="toast.type === 'error' ? 'assertive' : 'polite'"
      :data-test="`toast-${toast.type}`"
    >
      <span
        :class="['text-base leading-none mt-0.5 shrink-0', styleFor(toast.type).iconClass]"
        aria-hidden="true"
      >
        {{ styleFor(toast.type).icon }}
      </span>
      <div class="flex-1 min-w-0">
        <p
          v-if="toast.title"
          class="text-xs uppercase tracking-wider text-gray-400 truncate"
        >
          {{ toast.title }}
        </p>
        <p class="text-sm break-words whitespace-pre-wrap">{{ toast.body }}</p>
      </div>
      <button
        type="button"
        @click="onClose(toast.id)"
        class="text-gray-500 hover:text-gray-200 text-base leading-none shrink-0"
        :aria-label="`Dismiss ${toast.type} toast`"
        data-test="toast-dismiss"
      >
        ✕
      </button>
    </div>
  </div>
</template>
