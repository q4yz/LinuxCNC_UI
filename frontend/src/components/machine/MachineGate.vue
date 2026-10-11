<script setup lang="ts">
// Gates a machine-level widget on the shared machine-online heartbeat
// (``composables/useMachineOnline.ts``). While the machine is not
// online it says *why* (``offlineReason``) and offers the action that
// fits: Start when stopped, Stop when LinuxCNC runs but the machine
// backend does not respond, nothing while a transition is in progress.

import { computed } from "vue";
import { useMachineOnline } from "../../composables/useMachineOnline";
import { BaseButton } from "../../ui/index.ts";

const props = withDefaults(defineProps<{ label?: string }>(), { label: "Machine" });

const { isMachineOnline, isStarting, isStopping, offlineReason, runningIni, wakeMachine, stopMachine } =
  useMachineOnline();

const message = computed(() => {
  switch (offlineReason.value) {
    case "starting":
      return "LinuxCNC is starting…";
    case "connecting":
      return "Connecting to LinuxCNC…";
    case "stopping":
      return "LinuxCNC is stopping…";
    case "external":
      return `${props.label} is offline — LinuxCNC is running from another process${
        runningIni.value ? ` (${runningIni.value})` : ""
      }, not from this UI. Terminate it before starting the machine here.`;
    case "waiting":
      return "LinuxCNC is running — waiting for the machine backend…";
    case "unresponsive":
      return "LinuxCNC is running, but the machine backend is not responding.";
    case "system-offline":
      return "The system service is not reachable — check the connection to the machine.";
    default:
      return `${props.label} is currently offline. Start the machine to view these controls.`;
  }
});

const busy = computed(() =>
  ["starting", "connecting", "stopping", "waiting"].includes(offlineReason.value ?? ""),
);
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

  <!-- OFFLINE: why, plus the action that fits. -->
  <div
    v-else-if="isMachineOnline === false"
    data-testid="machine-gate-offline"
    :data-reason="offlineReason"
    class="rounded-lg border bg-gray-900 p-6 text-center"
    :class="offlineReason === 'unresponsive' || offlineReason === 'system-offline' ? 'border-red-700' : 'border-amber-700'"
    role="status"
    aria-live="polite"
  >
    <p class="flex items-center justify-center gap-2 text-gray-300">
      <span
        v-if="busy"
        class="h-4 w-4 animate-spin rounded-full border-2 border-gray-500 border-t-amber-300"
        aria-hidden="true"
      ></span>
      {{ message }}
    </p>
    <BaseButton
      v-if="offlineReason === 'stopped' || offlineReason === 'external'"
      variant="primary"
      class="mt-4"
      data-testid="machine-gate-start"
      :loading="isStarting"
      @click="wakeMachine()"
    >
      {{ isStarting ? "Starting…" : "Start machine" }}
    </BaseButton>
    <BaseButton
      v-else-if="offlineReason === 'unresponsive'"
      variant="danger"
      class="mt-4"
      data-testid="machine-gate-stop"
      :loading="isStopping"
      @click="stopMachine()"
    >
      Stop LinuxCNC
    </BaseButton>
  </div>

  <!-- ONLINE: render the heavy machine UI. -->
  <slot v-else />
</template>
