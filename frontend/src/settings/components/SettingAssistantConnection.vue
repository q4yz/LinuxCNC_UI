<script setup lang="ts">
// Settings → Assistant: how to add this machine to an AI assistant, and
// whether the MCP server is offering it tools right now.
//
// The address is this page's own origin + the MCP path: the UI and /mcp
// are served by the same host (nginx, or the dev proxy).

import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { agentConfirmationsFacade, type AgentStatus } from "../../facades/agentConfirmationsFacade";
import type { AssistantConnectionSetting } from "../types/AssistantConnectionSetting";

defineProps<{ setting: AssistantConnectionSetting }>();

/** How often the status refreshes while the tab is open (ms). */
const REFRESH_MS = 3000;

const status = ref<AgentStatus | null>(null);
const unreachable = ref(false);
const copied = ref<string | null>(null);
let timer: ReturnType<typeof setInterval> | null = null;

const origin = typeof window !== "undefined" ? window.location.origin : "";
const isLocalhost = typeof window !== "undefined" && ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
const url = computed(() => `${origin}${status.value?.mcpPath ?? "/mcp"}`);

const machineTools = computed(() => status.value?.tools.machine ?? 0);
const systemTools = computed(() => status.value?.tools.system ?? 0);
const healthy = computed(() => !!status.value?.running && machineTools.value + systemTools.value > 0);

const claudeCode = computed(() => `claude mcp add --transport http linuxcnc ${url.value}`);
const claudeDesktop = computed(() => {
  const args = ["-y", "mcp-remote", url.value];
  if (url.value.startsWith("http:")) args.push("--allow-http");
  return JSON.stringify({ mcpServers: { linuxcnc: { command: "npx", args } } }, null, 2);
});

async function refresh(): Promise<void> {
  try {
    status.value = await agentConfirmationsFacade.status();
    unreachable.value = false;
  } catch {
    unreachable.value = true;
  }
}

/** Copy, also on plain http (no Clipboard API outside secure contexts). */
async function copy(id: string, text: string): Promise<void> {
  let ok = false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      ok = true;
    }
  } catch {
    ok = false;
  }
  if (!ok) {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try {
      ok = document.execCommand("copy");
    } catch {
      ok = false;
    }
    area.remove();
  }
  copied.value = ok ? id : null;
  if (ok) setTimeout(() => (copied.value = copied.value === id ? null : copied.value), 1500);
}

onMounted(() => {
  void refresh();
  timer = setInterval(refresh, REFRESH_MS);
});
onBeforeUnmount(() => {
  if (timer !== null) clearInterval(timer);
});
</script>

<template>
  <div class="space-y-4 text-sm" data-testid="setting-assistant-connection">
    <!-- Status -->
    <div class="flex items-start gap-2 rounded border border-gray-700 bg-gray-900/60 p-3" data-testid="assistant-status">
      <span
        class="mt-1 inline-block h-2.5 w-2.5 shrink-0 rounded-full"
        :class="unreachable ? 'bg-red-500' : healthy ? 'bg-green-500' : 'bg-amber-500'"
      />
      <div class="min-w-0 text-gray-300">
        <template v-if="unreachable">The system service does not answer, so the MCP server is unreachable.</template>
        <template v-else-if="!status">Checking…</template>
        <template v-else-if="!status.running">The MCP server is not running. Restart the system service.</template>
        <template v-else>
          <div>
            MCP server running: <span class="font-semibold text-gray-100">{{ machineTools }}</span> machine and
            <span class="font-semibold text-gray-100">{{ systemTools }}</span> system tools.
            <template v-if="status.actionsAllowed">{{ status.toolsNeedingApproval }} of them wait for your approval.</template>
            <template v-else>Actions are switched off (read-only, plus the E-stop).</template>
          </div>
          <div v-if="machineTools === 0" class="text-xs text-amber-300">Machine tools appear while LinuxCNC is running.</div>
          <div v-if="status.pending > 0" class="text-xs text-amber-300">
            {{ status.pending }} action(s) waiting in the assistant panel.
          </div>
        </template>
      </div>
    </div>

    <!-- Address -->
    <div>
      <div class="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">MCP address</div>
      <div class="flex items-center gap-2">
        <code class="min-w-0 flex-1 break-all rounded bg-gray-950 px-2 py-1.5 font-mono text-xs text-gray-100" data-testid="assistant-mcp-url">{{ url }}</code>
        <button type="button" class="shrink-0 rounded bg-gray-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-600" @click="copy('url', url)">
          {{ copied === "url" ? "Copied" : "Copy" }}
        </button>
      </div>
      <p v-if="isLocalhost" class="mt-1 text-xs text-amber-300">
        You opened the UI on this computer: an assistant on another computer needs this machine's network address instead of
        "localhost".
      </p>
      <p class="mt-1 text-xs text-gray-500">
        Streamable HTTP, no login. The assistant gets the "agent" role: it reads everything and can engage the E-stop;
        anything else is shown to you in the assistant panel first.
      </p>
    </div>

    <!-- Claude Code -->
    <div>
      <div class="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Claude Code</div>
      <p class="mb-1 text-xs text-gray-400">Run in a terminal on the computer where you use Claude Code:</p>
      <div class="flex items-start gap-2">
        <pre class="min-w-0 flex-1 overflow-x-auto rounded bg-gray-950 p-2 font-mono text-xs text-gray-100" data-testid="assistant-claude-code">{{ claudeCode }}</pre>
        <button type="button" class="shrink-0 rounded bg-gray-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-600" @click="copy('code', claudeCode)">
          {{ copied === "code" ? "Copied" : "Copy" }}
        </button>
      </div>
    </div>

    <!-- Claude Desktop -->
    <div>
      <div class="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Claude Desktop</div>
      <p class="mb-1 text-xs text-gray-400">
        Settings → Developer → Edit Config, add this to <code>claude_desktop_config.json</code> (needs Node.js), then restart
        Claude Desktop:
      </p>
      <div class="flex items-start gap-2">
        <pre class="min-w-0 flex-1 overflow-x-auto rounded bg-gray-950 p-2 font-mono text-xs text-gray-100" data-testid="assistant-claude-desktop">{{ claudeDesktop }}</pre>
        <button type="button" class="shrink-0 rounded bg-gray-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-600" @click="copy('desktop', claudeDesktop)">
          {{ copied === "desktop" ? "Copied" : "Copy" }}
        </button>
      </div>
    </div>

    <!-- Others -->
    <div>
      <div class="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Other MCP clients</div>
      <p class="text-xs text-gray-400">
        Add a remote MCP server of type "Streamable HTTP" (sometimes just "HTTP") with the address above.
      </p>
    </div>
  </div>
</template>
