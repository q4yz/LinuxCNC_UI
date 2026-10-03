<script setup lang="ts">
// Debug: every HAL pin with its state, in the Visual HAL editor's own
// pin tree (``PinTreeItem`` + ``buildPinTree``).
//
// The pin *set* is fixed while LinuxCNC runs, so it comes from the same
// layout the editor uses (``loadHalLayout``). Only the *values* change;
// they come from ``GET /api/v1/hal/pins`` — a fresh, uncached read. Not
// live: the values are a snapshot from "read at"; Refresh re-reads.

import { computed, onMounted, ref } from "vue";
import { BaseButton } from "../../ui";
import PinTreeItem from "../../views/hal-visual-editor/PinTreeItem.vue";
import { buildPinTree, collectAutoExpandPaths } from "../../views/hal-visual-editor/pinTree";
import { loadHalLayout } from "../../views/hal-visual-editor/loadHalData";
import type { HalPin } from "../../views/hal-visual-editor/types";
import HalVisualService from "../../facades/halFacade";

type Direction = "all" | "in" | "out";

const pins = ref<HalPin[]>([]);
const values = ref<Record<string, boolean | number | null>>({});
const readAt = ref<string | null>(null);
const loading = ref(false);
const error = ref("");

const search = ref("");
const direction = ref<Direction>("all");
const expanded = ref(new Set<string>());
const noSelection = new Set<string>();

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

function toggleFolder(path: string) {
  const next = new Set(expanded.value);
  if (next.has(path)) next.delete(path);
  else next.add(path);
  expanded.value = next;
}

async function refreshValues(): Promise<void> {
  const states = await HalVisualService.fetchPinStates();
  if (!states) {
    error.value = "Could not read the HAL pin values.";
    return;
  }
  const map: Record<string, boolean | number | null> = {};
  for (const pin of states.pins ?? []) map[pin.id] = pin.value ?? null;
  values.value = map;
  readAt.value = states.read_at;
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

const readAtLabel = computed(() => (readAt.value ? new Date(readAt.value).toLocaleTimeString() : "—"));

onMounted(load);
</script>

<template>
  <div class="rounded-lg border border-gray-700 bg-gray-800 p-4 space-y-3" data-test="hal-pin-state-panel">
    <header class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold text-gray-100">HAL pins</h2>
        <p class="text-xs text-gray-400">
          {{ visiblePins.length }} pin(s), {{ trueCount }} bit(s) TRUE · values read at {{ readAtLabel }} (not live)
        </p>
      </div>
      <BaseButton variant="secondary" size="sm" :loading="loading" data-test="hal-pin-state-refresh" @click="load">
        Refresh values
      </BaseButton>
    </header>

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
          @toggle="toggleFolder"
      />
      <p v-if="!loading && visiblePins.length === 0" class="py-4 text-center text-xs text-gray-500">No pins.</p>
    </div>
  </div>
</template>
