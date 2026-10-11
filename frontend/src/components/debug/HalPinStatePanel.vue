<script setup lang="ts">
// Debug: every HAL pin with its state, in the Visual HAL editor's own
// pin tree (``PinTreeItem`` + ``buildPinTree``), plus the oscilloscope.
//
// The pin *set* is fixed while LinuxCNC runs, so it comes from the same
// layout the editor uses (``loadHalLayout``). Values are live: about
// once a second, only for the pins actually on screen (open folders),
// and only while this panel is in view and the browser tab is visible
// (``POST /api/v1/hal/pins/values`` — in-process reads, no ``halcmd``).
//
// Each pin's ∿ button adds it to / removes it from the oscilloscope
// (``scope/HalScope.vue``), which streams fast samples over a WebSocket.

import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref } from "vue";
import { BaseButton } from "../../ui";
import PinTreeItem from "../../views/hal-visual-editor/PinTreeItem.vue";
import { buildPinTree, collectAutoExpandPaths, type PinTreeNode } from "../../views/hal-visual-editor/pinTree";
import { loadHalLayout } from "../../views/hal-visual-editor/loadHalData";
import type { HalPin } from "../../views/hal-visual-editor/types";
import HalVisualService from "../../facades/halFacade";
import { useConsoleStore } from "../../stores/console";
// Debug-only and canvas-heavy: its own chunk, loaded with this panel —
// keeps the main bundle under the PWA precache limit (2 MiB).
const HalScope = defineAsyncComponent(() => import("./scope/HalScope.vue"));

type Direction = "all" | "in" | "out";

/** Live value poll period while the panel is visible. */
const POLL_MS = 1000;
/** The scope samples this many pins at most (backend limit). */
const MAX_SCOPE_PINS = 16;

const pins = ref<HalPin[]>([]);
const values = ref<Record<string, boolean | number | null>>({});
const readAt = ref<string | null>(null);
const loading = ref(false);
const error = ref("");
const live = ref(true);

const search = ref("");
const direction = ref<Direction>("all");
const expanded = ref(new Set<string>());
const noSelection = new Set<string>();

const scopePins = ref<string[]>([]);
const scopeIds = computed(() => new Set(scopePins.value));

function matchesSearch(pin: HalPin, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    pin.fullName.toLowerCase().includes(q) ||
    (pin.componentName ?? "").toLowerCase().includes(q) ||
    (pin.description ?? "").toLowerCase().includes(q)
  );
}

const visiblePins = computed(() =>
  pins.value.filter(
    (pin) => (direction.value === "all" || pin.direction === direction.value) && matchesSearch(pin, search.value),
  ),
);
const tree = computed(() => buildPinTree(visiblePins.value));
const autoExpand = computed(() =>
  collectAutoExpandPaths(visiblePins.value, null, search.value.trim().length > 0),
);
const trueCount = computed(() => visiblePins.value.filter((p) => values.value[p.id] === true).length);

/** Pins actually rendered: every ancestor folder open. */
const shownPinIds = computed(() => {
  const ids: string[] = [];
  const walk = (nodes: PinTreeNode[]) => {
    for (const node of nodes) {
      if (node.kind === "pin") ids.push(node.pin.id);
      else if (autoExpand.value.has(node.path) || expanded.value.has(node.path)) walk(node.children);
    }
  };
  walk(tree.value.children);
  return ids;
});

function toggleFolder(path: string) {
  const next = new Set(expanded.value);
  if (next.has(path)) next.delete(path);
  else next.add(path);
  expanded.value = next;
}

function toggleScope(pin: HalPin): void {
  if (scopeIds.value.has(pin.id)) {
    scopePins.value = scopePins.value.filter((id) => id !== pin.id);
    return;
  }
  if (scopePins.value.length >= MAX_SCOPE_PINS) {
    useConsoleStore().warning(`The oscilloscope shows at most ${MAX_SCOPE_PINS} pins.`, { popup: true });
    return;
  }
  scopePins.value = [...scopePins.value, pin.id];
}

async function refreshValues(): Promise<void> {
  const ids = shownPinIds.value;
  const result = await HalVisualService.readPinValues(ids);
  if (!result) {
    error.value = "Could not read the HAL pin values.";
    return;
  }
  error.value = "";
  // Merge: values of folded-away pins stay as last read.
  values.value = { ...values.value, ...result.values };
  readAt.value = result.read_at;
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    if (pins.value.length === 0) {
      const layout = await loadHalLayout();
      if (!layout) {
        error.value = "Could not load the HAL pin list.";
        return;
      }
      pins.value = layout.pins;
    }
    await refreshValues();
  } finally {
    loading.value = false;
  }
}

// --- live polling: only while on screen ---------------------------------- //

const root = ref<HTMLElement | null>(null);
const inView = ref(true);
const tabVisible = ref(typeof document === "undefined" || document.visibilityState !== "hidden");
const polling = computed(() => live.value && inView.value && tabVisible.value && pins.value.length > 0);
let pollTimer: ReturnType<typeof setTimeout> | null = null;
let observer: IntersectionObserver | null = null;

async function pollLoop(): Promise<void> {
  pollTimer = null;
  if (polling.value && !loading.value) await refreshValues();
  pollTimer = setTimeout(pollLoop, POLL_MS);
}

function onVisibilityChange(): void {
  tabVisible.value = document.visibilityState !== "hidden";
}

onMounted(async () => {
  document.addEventListener("visibilitychange", onVisibilityChange);
  if (root.value && typeof IntersectionObserver !== "undefined") {
    observer = new IntersectionObserver((entries) => {
      inView.value = entries.some((entry) => entry.isIntersecting);
    });
    observer.observe(root.value);
  }
  await load();
  pollTimer = setTimeout(pollLoop, POLL_MS);
});

onBeforeUnmount(() => {
  document.removeEventListener("visibilitychange", onVisibilityChange);
  observer?.disconnect();
  if (pollTimer) clearTimeout(pollTimer);
});

const readAtLabel = computed(() => (readAt.value ? new Date(readAt.value).toLocaleTimeString() : "—"));
const liveLabel = computed(() => {
  if (!live.value) return "paused";
  if (!polling.value) return "paused while hidden";
  return "live, 1 Hz";
});
</script>

<template>
  <div ref="root" class="rounded-lg border border-gray-700 bg-gray-800 p-4 space-y-3" data-test="hal-pin-state-panel">
    <header class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold text-gray-100">HAL pins</h2>
        <p class="text-xs text-gray-400" data-test="hal-pin-state-summary">
          {{ visiblePins.length }} pin(s), {{ trueCount }} bit(s) TRUE · {{ shownPinIds.length }} on screen ·
          read {{ readAtLabel }} ({{ liveLabel }})
        </p>
      </div>
      <div class="flex items-center gap-2">
        <label class="flex items-center gap-1.5 text-xs text-gray-300">
          <input v-model="live" type="checkbox" data-test="hal-pin-state-live" />
          Live
        </label>
        <BaseButton variant="secondary" size="sm" :loading="loading" data-test="hal-pin-state-refresh" @click="load">
          Refresh values
        </BaseButton>
      </div>
    </header>

    <HalScope v-model="scopePins" />

    <div class="flex flex-wrap items-center gap-2">
      <input
          v-model="search"
          type="text"
          placeholder="Filter pins…"
          class="min-w-0 flex-1 rounded border border-gray-600 bg-gray-900 px-2 py-1.5 font-mono text-sm text-gray-200 placeholder:text-gray-500 focus:border-blue-500 focus:outline-none"
          data-test="hal-pin-state-search"
      />
      <div class="flex overflow-hidden rounded border border-gray-600 text-xs" role="radiogroup" aria-label="Pin direction">
        <button
            v-for="d in (['all', 'in', 'out'] as const)"
            :key="d"
            type="button"
            role="radio"
            :aria-checked="direction === d"
            class="px-2.5 py-1.5 uppercase tracking-wide"
            :class="direction === d ? 'bg-blue-600 text-white' : 'bg-gray-900 text-gray-400 hover:text-gray-200'"
            @click="direction = d"
        >
          {{ d }}
        </button>
      </div>
    </div>

    <p v-if="error" class="text-xs text-red-300" role="alert">{{ error }}</p>

    <div class="max-h-[60vh] overflow-y-auto space-y-0.5 pr-1">
      <PinTreeItem
          v-for="child in tree.children"
          :key="child.kind === 'folder' ? `f:${child.path}` : `p:${child.pin.id}`"
          :node="child"
          :expanded="expanded"
          :auto-expand="autoExpand"
          :match-suffix="null"
          :selected-ids="noSelection"
          :depth="0"
          :values="values"
          :scope-ids="scopeIds"
          @toggle="toggleFolder"
          @scope="toggleScope"
      />
      <p v-if="!loading && visiblePins.length === 0" class="py-4 text-center text-xs text-gray-500">No pins.</p>
    </div>
  </div>
</template>
