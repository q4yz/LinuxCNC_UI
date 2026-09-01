<script setup lang="ts">
// "Connection appears stuck" modal.
//
// Pops after the base-thread watchdog in ``stores/baseThread.ts``
// observes a gap larger than ``PENDING_TIMEOUT_MS`` (6 s) without a
// successful snapshot. The two buttons cover the two failure modes:
//
//   * **Refresh now** — fires an immediate ``store.refresh()`` (also
//     re-arms the watchdog via ``markSnapshotPending()``).
//   * **Reload page** — nuclear option for a hung backend that
//     ``refresh()`` cannot rescue; reloads the SPA so the JS layer
//     starts clean and the user keeps their place in the URL.
//
// Dismissing the cross marks the dialog as dismissed for the
// cooldown defined by ``PENDING_DISMISS_COOLDOWN_MS`` in the store
// (60 s); the underlying ``pendingSince`` is not cleared, only the
// modal is hidden — the operator still sees the "stuck for Ns"
// badge in the EStop header until the snapshot recovers.

import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useBaseThreadStore } from "../stores/baseThread";

const store = useBaseThreadStore();
const { pendingSince, secondsSinceLastSnapshot } = storeToRefs(store);

const open = computed<boolean>(() => pendingSince.value !== null);

function refreshNow(): void {
  store.rearmPendingPrompt();
  void store.refresh();
}

function reloadPage(): void {
  if (typeof window !== "undefined") {
    window.location.reload();
  }
}

function dismiss(): void {
  store.dismissPendingPrompt();
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="pending-snapshot-title"
      @click.self="dismiss"
    >
      <section class="w-full max-w-md rounded-lg border border-amber-600 bg-gray-900 p-6 text-white shadow-2xl">
        <div class="flex items-start justify-between gap-4">
          <h2 id="pending-snapshot-title" class="text-lg font-semibold text-amber-300">
            Connection appears stuck
          </h2>
          <button
            type="button"
            class="text-xl text-gray-400 hover:text-white"
            aria-label="Dismiss"
            @click="dismiss"
          >
            &times;
          </button>
        </div>

        <p class="mt-4 text-gray-200">
          The dashboard has not received a snapshot in
          <span class="font-mono font-semibold text-amber-300">{{ secondsSinceLastSnapshot }}s</span>.
          The backend, the proxy, or the network may be unresponsive.
        </p>

        <p class="mt-2 text-sm text-gray-400">
          Try a manual refresh first. If that does not recover,
          reloading the page forces a clean SPA restart while
          keeping the current URL.
        </p>

        <div class="mt-6 flex flex-wrap justify-end gap-3">
          <button
            type="button"
            class="rounded border border-gray-600 px-4 py-2 text-sm font-semibold text-gray-200 hover:bg-gray-800"
            @click="dismiss"
          >
            Dismiss
          </button>
          <button
            type="button"
            class="rounded border border-amber-600 px-4 py-2 text-sm font-semibold text-amber-200 hover:bg-amber-950"
            @click="reloadPage"
          >
            Reload page
          </button>
          <button
            type="button"
            class="rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500"
            @click="refreshNow"
          >
            Refresh now
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>
