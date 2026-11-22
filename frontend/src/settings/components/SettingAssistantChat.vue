<script setup lang="ts">
// Settings → Assistant: the in-app assistant's Anthropic API key (write-only),
// model and effort. Saved on the system service (not in the UI settings,
// which the agent can read); a change re-installs the chat panel's agent.

import { onMounted, ref } from "vue";

import { assistantFacade, type AssistantConfig } from "../../facades/assistantFacade";
import { useAgentStore } from "../../stores/agentStore";
import type { PanelSetting } from "../types/PanelSetting";

defineProps<{ setting: PanelSetting }>();

const agent = useAgentStore();
const config = ref<AssistantConfig | null>(null);
const unreachable = ref(false);
const keyInput = ref("");
const saving = ref(false);
const message = ref("");
const failed = ref(false);

const EFFORT_LABEL: Record<string, string> = {
  low: "Low (quick answers)",
  medium: "Medium (recommended)",
  high: "High (think harder)",
};

async function load(): Promise<void> {
  try {
    config.value = await assistantFacade.config();
    unreachable.value = false;
  } catch {
    unreachable.value = true;
  }
}

async function save(change: { apiKey?: string; model?: string; effort?: string }, done: string): Promise<void> {
  saving.value = true;
  const { result, config: next } = await assistantFacade.updateConfig(change);
  saving.value = false;
  failed.value = !result.ok;
  message.value = result.ok ? done : (result.failureReason ?? "Could not save.");
  if (next) config.value = next;
  if (result.ok) {
    keyInput.value = "";
    await agent.refreshTransport();
  }
}

function saveKey(): void {
  const key = keyInput.value.trim();
  if (key) void save({ apiKey: key }, "API key saved. The assistant panel now answers with Claude.");
}

onMounted(load);
</script>

<template>
  <div class="space-y-4 text-sm" data-testid="setting-assistant-chat">
    <p v-if="unreachable" class="text-red-400">The system service does not answer.</p>
    <template v-else-if="config">
      <!-- Key -->
      <div>
        <div class="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Anthropic API key</div>
        <div class="mb-2 flex items-center gap-2 text-gray-300" data-testid="assistant-key-state">
          <span class="inline-block h-2.5 w-2.5 rounded-full" :class="config.configured ? 'bg-green-500' : 'bg-gray-500'" />
          <template v-if="config.keySource === 'stored'">A key is saved ({{ config.keyHint }}).</template>
          <template v-else-if="config.keySource === 'environment'">Using the key from ANTHROPIC_API_KEY ({{ config.keyHint }}).</template>
          <template v-else>No key yet: the chat panel cannot answer.</template>
        </div>
        <form class="flex gap-2" @submit.prevent="saveKey">
          <input
            v-model="keyInput"
            type="password"
            autocomplete="off"
            data-testid="assistant-key-input"
            class="min-w-0 flex-1 rounded border border-gray-600 bg-gray-900 px-2 py-1.5 font-mono text-xs text-gray-100 placeholder-gray-500 focus:border-blue-500 focus:outline-none"
            :placeholder="config.keySource === 'stored' ? 'Paste a new key to replace it' : 'sk-ant-...'"
          />
          <button
            type="submit"
            data-testid="assistant-key-save"
            class="shrink-0 rounded bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-500 disabled:opacity-40"
            :disabled="saving || !keyInput.trim()"
          >
            Save key
          </button>
          <button
            v-if="config.keySource === 'stored'"
            type="button"
            data-testid="assistant-key-remove"
            class="shrink-0 rounded bg-gray-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-40"
            :disabled="saving"
            @click="save({ apiKey: '' }, 'API key removed.')"
          >
            Remove
          </button>
        </form>
        <p class="mt-1 text-xs text-gray-500">
          Create one at console.anthropic.com (API keys). The machine needs internet access to reach the Anthropic API.
        </p>
      </div>

      <!-- Model / effort -->
      <div class="flex flex-wrap gap-4">
        <label class="flex min-w-[14rem] flex-1 flex-col gap-1">
          <span class="text-xs font-semibold uppercase tracking-wide text-gray-400">Model</span>
          <select
            :value="config.model"
            data-testid="assistant-model"
            class="rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-sm text-gray-100 focus:border-blue-500 focus:outline-none"
            :disabled="saving"
            @change="save({ model: ($event.target as HTMLSelectElement).value }, 'Model saved.')"
          >
            <option v-for="m in config.models" :key="m.id" :value="m.id">{{ m.label }}</option>
          </select>
        </label>
        <label class="flex min-w-[14rem] flex-1 flex-col gap-1">
          <span class="text-xs font-semibold uppercase tracking-wide text-gray-400">Effort</span>
          <select
            :value="config.effort"
            data-testid="assistant-effort"
            class="rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-sm text-gray-100 focus:border-blue-500 focus:outline-none"
            :disabled="saving"
            @change="save({ effort: ($event.target as HTMLSelectElement).value }, 'Effort saved.')"
          >
            <option v-for="e in config.efforts" :key="e" :value="e">{{ EFFORT_LABEL[e] ?? e }}</option>
          </select>
        </label>
      </div>

      <p v-if="message" class="text-xs" :class="failed ? 'text-red-400' : 'text-green-400'" data-testid="assistant-config-message">{{ message }}</p>
    </template>
    <p v-else class="text-gray-400">Loading…</p>
  </div>
</template>
