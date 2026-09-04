<script setup lang="ts">
// System/machine UI boundary gate.
//
// The split backend means two availability domains: the system
// service (:8001, always up) and the machine service (:8000,
// sometimes down). This component renders the machine-side UI only
// when the global heartbeat (``composables/useMachineOnline.ts``)
// has positively confirmed :8000 is reachable:
//
//   * ``null`` (loading) → neutral skeleton. Deliberately NOT the
//     machine UI: treating unknown as online would mount the
//     camera MJPEG, the WebSocket and 1 Hz polls against a possibly
//     dead port — the "reverse flash" of 502 spam. One probe round
//     trip (≤ 2 s timeout, usually instant) resolves it.
//   * ``false`` (offline) → amber card with an optional Start
//     button (``wakeMachine()`` via the always-up system service).
//     Unmounting machine children via ``v-if`` also kills their
//     network traffic — e.g. the camera's MJPEG ``<img>`` is
//     removed from the DOM, which aborts the hanging stream.
//   * ``true`` (online) → the default slot.
//
// ``label`` names the gated group in the loading/offline copy
// (e.g. "Camera", "DRO"); defaults to "Machine".

import { useMachineOnline } from "../../composables/useMachineOnline";
import { BaseButton } from "../../ui/index.ts";

withDefaults(defineProps<{ label?: string }>(), { label: "Machine" });

const { isMachineOnline, isStarting, wakeMachine } = useMachineOnline();
</script>

<template>
  <!-- LOADING: neutral skeleton while the first probe settles. -->
  <div
    v-if="isMachineOnline === null"
    data-testid="machine-gate-loading"
    class="rounded-lg border border-gray-700 bg-gray-800/60 p-6"
    role="status"
    aria-live="polite"
  >
    <div class="flex items-center gap-3 text-gray-400">
      <div
        class="h-4 w-4 animate-spin rounded-full border-2 border-gray-500 border-t-gray-300"
        aria-hidden="true"
      ></div>
      <span class="font-mono text-xs uppercase tracking-widest">
        {{ label }} — checking…
      </span>
    </div>
    <div class="mt-4 space-y-2" aria-hidden="true">
      <div class="h-3 w-3/4 animate-pulse rounded bg-gray-700"></div>
      <div class="h-3 w-1/2 animate-pulse rounded bg-gray-700"></div>
    </div>
  </div>

  <!-- OFFLINE: amber card + Start (spawn via the system service). -->
  <div
    v-else-if="isMachineOnline === false"
    data-testid="machine-gate-offline"
    class="rounded-lg border border-amber-700 bg-gray-900 p-6 text-center"
    role="status"
    aria-live="polite"
  >
    <p class="text-gray-300">
      {{ label }} is currently offline.
      Start the machine to view these controls.
    </p>
    <BaseButton
      variant="primary"
      class="mt-4"
      data-testid="machine-gate-start"
      :loading="isStarting"
      @click="wakeMachine()"
    >
      {{ isStarting ? "Starting…" : "Start machine" }}
    </BaseButton>
  </div>

  <!-- ONLINE: render the heavy machine UI. -->
  <slot v-else />
</template>
