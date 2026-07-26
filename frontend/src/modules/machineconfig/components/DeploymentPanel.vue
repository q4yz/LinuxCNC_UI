<script setup>
// DeploymentPanel — bottom-of-page panel that promotes the staged
// artifacts into ``machine_config/active``. Includes the "Confirm
// Flash" toggle that the backend's deploy endpoint requires by
// default (when ``require_confirm_flash`` is enabled in module
// settings).

import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useMachineConfigStore } from "../store.js";

const store = useMachineConfigStore();
const { confirmFlash, stagedFiles, lastDeploySummary, isBusy } = storeToRefs(store);

const canDeploy = computed(() => stagedFiles.value.length > 0);

async function onDeploy() {
  await store.deploy();
}
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden">
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        <span class="mr-2">🚀</span> Deployment Controls
      </h2>
    </div>

    <div class="p-4 space-y-4">
      <div class="rounded border border-yellow-700/60 bg-yellow-900/20 p-3 text-yellow-200 text-sm">
        <p class="font-semibold mb-1">⚠️ Flash requirement</p>
        <p class="text-yellow-100/80">
          When the active machine uses a remote controller (e.g. Remora) the
          <code class="bg-yellow-900/60 px-1 rounded">remora.json</code> payload must
          be flashed <em>before</em> deploying. Tick the box below to acknowledge
          the flash and unlock the Deploy button.
        </p>
      </div>

      <label class="flex items-center gap-3 text-sm text-gray-200 cursor-pointer select-none">
        <input
          v-model="confirmFlash"
          type="checkbox"
          class="w-5 h-5 rounded bg-gray-900 border-gray-600 text-blue-500 focus:ring-blue-500"
        />
        <span>Confirm Flash — the remote controller has been flashed with the staged payload.</span>
      </label>

      <div class="flex items-center justify-between gap-3 pt-2 border-t border-gray-700">
        <button
          type="button"
          class="px-4 py-2 rounded font-semibold bg-red-600 hover:bg-red-500 disabled:bg-red-900 disabled:cursor-not-allowed text-white"
          :disabled="isBusy || !canDeploy"
          @click="onDeploy"
        >
          {{ isBusy ? 'Deploying…' : 'Deploy' }}
        </button>
        <p class="text-xs text-gray-400">
          After deploy, restart the LinuxCNC backend to activate the new configuration.
        </p>
      </div>

      <div
        v-if="lastDeploySummary"
        class="rounded border border-green-700/60 bg-green-900/20 p-3 text-green-200 text-xs font-mono"
      >
        {{ lastDeploySummary.message }}
        <span v-if="lastDeploySummary.deployed && lastDeploySummary.deployed.length > 0">
          — copied: {{ lastDeploySummary.deployed.join(', ') }}
        </span>
      </div>
    </div>
  </div>
</template>