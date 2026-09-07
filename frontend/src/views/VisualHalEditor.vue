<script setup lang="ts">
// Visual HAL editor — canvas-based logic wiring board.
//
// A live, READ-ONLY view over the real HAL world: pins and signals
// come from `GET /api/v1/hal/layout` (./hal-visual-editor/loadHalData.ts
// → facades/halFacade.ts). Existing backend signals are seeded onto
// the canvas as pre-wired pin nodes (wire labels = signal names);
// the drawers list the real IN/OUT pins. Blocks added in-session and
// any re-wiring are FRONTEND-ONLY state — nothing in this editor
// ever sends anything back to the backend; the Refresh button
// re-fetches and resets the canvas to backend truth.
//
// The whole editor is wrapped in MachineGate: HAL data lives on the
// machine backend (:8000), so the offline card shows when the
// machine is down and the layout re-fetches when it comes back.

import { computed, onMounted, ref, watch } from "vue";

import { Drawer, Icon } from "../ui/index.ts";
import MachineGate from "../components/machine/MachineGate.vue";
import { useMachineOnline } from "../composables/useMachineOnline";
import { useToast } from "../core/toast";
import { BLOCK_DEFINITIONS, BLOCK_MENU } from "./hal-visual-editor/blockDefinitions";
import { nodeHeight, portAnchor, NODE_WIDTH } from "./hal-visual-editor/layout";
import { loadHalLayout } from "./hal-visual-editor/loadHalData";
import { useHalCanvas } from "./hal-visual-editor/useHalCanvas";
import type { BlockKind, HalNode, HalPin, PinType, Port } from "./hal-visual-editor/types";

const canvas = useHalCanvas();
const toast = useToast();
const { isMachineOnline } = useMachineOnline();

// --- layout loading (real data, read-only) ---------------------------------

const loading = ref(false);
const loadError = ref<string | null>(null);
const pinCount = ref(0);
const signalCount = ref(0);

async function refresh(): Promise<void> {
  if (loading.value) return;
  loading.value = true;
  loadError.value = null;
  try {
    const data = await loadHalLayout();
    if (!data) {
      loadError.value = "Failed to load the HAL layout from the backend.";
      return;
    }
    // Reset to backend truth: in-session blocks/wires are discarded.
    canvas.reset();
    canvas.setPins(data.pins);
    canvas.seedSignals(data.signals);
    pinCount.value = data.pins.length;
    signalCount.value = data.signals.length;
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  if (isMachineOnline.value) void refresh();
});

// The gate unmounts the editor while the machine is offline; when it
// comes back online, pull a fresh layout.
watch(isMachineOnline, (next) => {
  if (next) void refresh();
});

// --- canvas geometry ------------------------------------------------------

const CANVAS_WIDTH = 3200;
const CANVAS_HEIGHT = 2000;
const canvasSizeStyle = { width: `${CANVAS_WIDTH}px`, height: `${CANVAS_HEIGHT}px` };

const contentEl = ref<HTMLElement | null>(null);

function localPoint(event: MouseEvent): { x: number; y: number } {
  const rect = contentEl.value?.getBoundingClientRect();
  if (!rect) return { x: 0, y: 0 };
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

function hasAddButton(node: HalNode): boolean {
  return BLOCK_DEFINITIONS[node.kind].variadicInputs;
}

function nodeStyle(node: HalNode) {
  return {
    left: `${node.x}px`,
    top: `${node.y}px`,
    width: `${NODE_WIDTH}px`,
    height: `${nodeHeight(node, hasAddButton(node))}px`,
  };
}

// --- FAB / block palette ----------------------------------------------------

const menuOpen = ref(false);

function onAddBlock(kind: BlockKind) {
  canvas.addNode(kind);
  menuOpen.value = false;
}

function onCanvasBackgroundMouseDown(event: MouseEvent) {
  if (event.target === event.currentTarget && menuOpen.value) {
    menuOpen.value = false;
  }
}

// --- node dragging ----------------------------------------------------------

function onNodeHeaderMouseDown(event: MouseEvent, node: HalNode) {
  if (event.button !== 0) return;
  const start = localPoint(event);
  const offsetX = start.x - node.x;
  const offsetY = start.y - node.y;

  function onMove(e: MouseEvent) {
    const p = localPoint(e);
    canvas.moveNode(node.id, Math.max(0, p.x - offsetX), Math.max(0, p.y - offsetY));
  }
  function onUp() {
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
  }
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
}

// --- port <-> port wiring (chaining blocks) ---------------------------------

interface PendingWire {
  fromPortId: string;
  x: number;
  y: number;
}
const pendingWire = ref<PendingWire | null>(null);
const rejectedPortId = ref<string | null>(null);
let rejectTimer: ReturnType<typeof setTimeout> | null = null;

function flashReject(portId: string) {
  rejectedPortId.value = portId;
  if (rejectTimer !== null) clearTimeout(rejectTimer);
  rejectTimer = setTimeout(() => {
    rejectedPortId.value = null;
    rejectTimer = null;
  }, 500);
}

const HIT_RADIUS = 16;
function findInputPortNear(point: { x: number; y: number }): { node: HalNode; port: Port } | null {
  let best: { node: HalNode; port: Port } | null = null;
  let bestDist = HIT_RADIUS;
  for (const node of canvas.nodes) {
    for (const port of node.inputs) {
      const anchor = portAnchor(node, port);
      const dist = Math.hypot(anchor.x - point.x, anchor.y - point.y);
      if (dist <= bestDist) {
        bestDist = dist;
        best = { node, port };
      }
    }
  }
  return best;
}

function onOutputDotMouseDown(event: MouseEvent, node: HalNode, port: Port) {
  if (event.button !== 0) return;
  const startClientX = event.clientX;
  const startClientY = event.clientY;
  let moved = false;
  pendingWire.value = { fromPortId: port.id, ...localPoint(event) };

  function onMove(e: MouseEvent) {
    if (!moved && Math.hypot(e.clientX - startClientX, e.clientY - startClientY) > 4) {
      moved = true;
    }
    pendingWire.value = { fromPortId: port.id, ...localPoint(e) };
  }

  function onUp(e: MouseEvent) {
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
    const dropPoint = localPoint(e);
    pendingWire.value = null;

    if (!moved) {
      openOutputDrawer(node, port);
      return;
    }
    const target = findInputPortNear(dropPoint);
    if (!target) return;
    const result = canvas.connectWire(port.id, target.port.id);
    if (!result.ok) {
      toast.error(result.message ?? "Connection rejected.");
      flashReject(target.port.id);
    }
  }

  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
}

// --- wire geometry (SVG) -----------------------------------------------------

function bezierPath(from: { x: number; y: number }, to: { x: number; y: number }): string {
  const dx = Math.max(60, Math.abs(to.x - from.x) / 2);
  return `M ${from.x} ${from.y} C ${from.x + dx} ${from.y}, ${to.x - dx} ${to.y}, ${to.x} ${to.y}`;
}

interface WireGeometry {
  id: string;
  d: string;
  mid: { x: number; y: number };
  label?: string;
}

const wireGeometry = computed<WireGeometry[]>(() => {
  return canvas.wires.flatMap((wire): WireGeometry[] => {
    const from = canvas.findPort(wire.fromPortId);
    const to = canvas.findPort(wire.toPortId);
    if (!from || !to) return [];
    const fromAnchor = portAnchor(from.node, from.port);
    const toAnchor = portAnchor(to.node, to.port);
    return [
      {
        id: wire.id,
        d: bezierPath(fromAnchor, toAnchor),
        mid: { x: (fromAnchor.x + toAnchor.x) / 2, y: (fromAnchor.y + toAnchor.y) / 2 },
        ...(wire.label ? { label: wire.label } : {}),
      },
    ];
  });
});

const pendingWireGeometry = computed(() => {
  if (!pendingWire.value) return null;
  const from = canvas.findPort(pendingWire.value.fromPortId);
  if (!from) return null;
  const fromAnchor = portAnchor(from.node, from.port);
  return bezierPath(fromAnchor, { x: pendingWire.value.x, y: pendingWire.value.y });
});

// --- pin picker drawers -------------------------------------------------------

const activeInputPortId = ref<string | null>(null);
const activeOutputPortId = ref<string | null>(null);

const activeInput = computed(() => (activeInputPortId.value ? canvas.findPort(activeInputPortId.value) : null));
const activeOutput = computed(() => (activeOutputPortId.value ? canvas.findPort(activeOutputPortId.value) : null));

function openInputDrawer(node: HalNode, port: Port) {
  activeOutputPortId.value = null;
  activeInputPortId.value = port.id;
}
function openOutputDrawer(node: HalNode, port: Port) {
  activeInputPortId.value = null;
  activeOutputPortId.value = port.id;
}
function closeInputDrawer() {
  activeInputPortId.value = null;
}
function closeOutputDrawer() {
  activeOutputPortId.value = null;
}

// Real machines expose hundreds of pins — both drawers filter on a
// free-text query over full name / component / description.
const inputSearch = ref("");
const outputSearch = ref("");

function matchesSearch(pin: HalPin, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    pin.fullName.toLowerCase().includes(q) ||
    (pin.componentName ?? "").toLowerCase().includes(q) ||
    (pin.description ?? "").toLowerCase().includes(q)
  );
}

const inputDrawerPins = computed<HalPin[]>(() => {
  if (!activeInputPortId.value) return [];
  return canvas
    .compatibleSourcePins(activeInputPortId.value)
    .filter((pin) => matchesSearch(pin, inputSearch.value));
});
const outputDrawerPins = computed<HalPin[]>(() => {
  if (!activeOutputPortId.value) return [];
  return canvas
    .compatibleTargetPins(activeOutputPortId.value)
    .filter((pin) => matchesSearch(pin, outputSearch.value));
});

// Where to drop a HAL pin's stand-in node the first time it's
// picked: hugging the requesting port's side of its block, so the
// new wire reads left-to-right (source pins land to the left of an
// input, target pins land to the right of an output).
function pinPlacementNear(node: HalNode, port: Port): { x: number; y: number } {
  const anchor = portAnchor(node, port);
  const dx = port.direction === "in" ? -(NODE_WIDTH + 70) : NODE_WIDTH + 70;
  return { x: Math.max(0, node.x + dx), y: Math.max(0, anchor.y - 22) };
}

function onPickSourcePin(pin: HalPin) {
  const found = activeInput.value;
  if (!found) return;
  const currentPinId = canvas.inputSourcePinId(found.port.id);
  if (currentPinId === pin.id) {
    canvas.disconnectPort(found.port.id);
    return;
  }
  if (canvas.isInputDriven(found.port.id)) {
    canvas.disconnectPort(found.port.id);
  }
  const result = canvas.connectToPin(found.port.id, pin, pinPlacementNear(found.node, found.port));
  if (!result.ok) {
    toast.error(result.message ?? "Connection rejected.");
    return;
  }
  closeInputDrawer();
}

function onToggleTargetPin(pin: HalPin) {
  const found = activeOutput.value;
  if (!found) return;
  if (canvas.outputTargetPinIds(found.port.id).includes(pin.id)) {
    const pinNode = canvas.findPinNode(pin.id);
    const wire = pinNode
      ? canvas.wires.find((w) => w.fromPortId === found.port.id && w.toPortId === pinNode.inputs[0]?.id)
      : undefined;
    if (wire) canvas.removeWire(wire.id);
    return;
  }
  const result = canvas.connectToPin(found.port.id, pin, pinPlacementNear(found.node, found.port));
  if (!result.ok) {
    toast.error(result.message ?? "Connection rejected.");
  }
}

// Only surfaces a driver that is another *gate* — a HAL-pin driver
// is already visible on the canvas and highlighted in the pin list
// below, so it doesn't need this separate callout.
const inputGateDriver = computed(() => {
  const found = activeInput.value;
  if (!found) return null;
  const wire = canvas.wires.find((w) => w.toPortId === found.port.id);
  if (!wire) return null;
  const from = canvas.findPort(wire.fromPortId);
  if (!from || from.node.kind === "hal-pin") return null;
  return `${from.node.label} · ${from.port.name}`;
});

// Wires from this output to other *gates* — chained-to-HAL-pin wires
// are represented by the checkbox list below instead.
const outputWires = computed(() => {
  const found = activeOutput.value;
  if (!found) return [];
  const result: { id: string; label: string }[] = [];
  for (const wire of canvas.wires) {
    if (wire.fromPortId !== found.port.id) continue;
    const to = canvas.findPort(wire.toPortId);
    if (to && to.node.kind !== "hal-pin") {
      result.push({ id: wire.id, label: `${to.node.label} · ${to.port.name}` });
    }
  }
  return result;
});

// --- presentation helpers ------------------------------------------------------

const TYPE_COLORS: Record<Exclude<PinType, "auto">, { border: string; bg: string; badge: string }> = {
  bit: { border: "border-green-400", bg: "bg-green-400", badge: "bg-green-900/60 text-green-300 border border-green-700" },
  float: { border: "border-blue-400", bg: "bg-blue-400", badge: "bg-blue-900/60 text-blue-300 border border-blue-700" },
  s32: { border: "border-amber-400", bg: "bg-amber-400", badge: "bg-amber-900/60 text-amber-300 border border-amber-700" },
  u32: { border: "border-purple-400", bg: "bg-purple-400", badge: "bg-purple-900/60 text-purple-300 border border-purple-700" },
};
const AUTO_COLOR = { border: "border-gray-400", bg: "bg-gray-400", badge: "bg-gray-700 text-gray-300 border border-gray-600" };

function colorFor(type: Exclude<PinType, "auto"> | null) {
  return type ? TYPE_COLORS[type] : AUTO_COLOR;
}

function typeBadgeClass(type: Exclude<PinType, "auto"> | null): string {
  return colorFor(type).badge;
}

function portDotClass(port: Port): string[] {
  const type = canvas.resolveType(port);
  const color = colorFor(type);
  const driven = port.direction === "in" ? canvas.isInputDriven(port.id) : canvas.isOutputDriving(port.id);
  const rejecting = rejectedPortId.value === port.id;
  return [
    "inline-block h-3 w-3 rounded-full border-2 shrink-0 transition-colors",
    rejecting ? "border-red-500 bg-red-500 hal-port-reject" : color.border,
    !rejecting && driven ? color.bg : "",
  ];
}

// Native tooltip on a port row: what it's connected to, if anything.
function portTitle(port: Port): string | undefined {
  if (port.direction === "in") return canvas.inputDriverLabel(port.id) ?? undefined;
  const targets: string[] = [];
  for (const wire of canvas.wires) {
    if (wire.fromPortId !== port.id) continue;
    const to = canvas.findPort(wire.toPortId);
    if (!to) continue;
    targets.push(to.node.kind === "hal-pin" ? to.node.label : `${to.node.label} · ${to.port.name}`);
  }
  return targets.length > 0 ? targets.join(", ") : undefined;
}

const CATEGORY_HEADER_CLASS: Record<string, string> = {
  signal: "bg-gray-700 text-gray-200",
  gate: "bg-blue-900/60 text-blue-200",
  memory: "bg-purple-900/60 text-purple-200",
  pin: "bg-teal-900/60 text-teal-200",
};

function headerClass(node: HalNode): string {
  return CATEGORY_HEADER_CLASS[BLOCK_DEFINITIONS[node.kind].category] ?? CATEGORY_HEADER_CLASS.gate;
}

// Type badge shown in a "hal-pin" node's header (its single port's
// type) — gates don't need this, their function implies "bit".
function pinNodeType(node: HalNode): Exclude<PinType, "auto"> | null {
  if (node.kind !== "hal-pin") return null;
  const port = node.inputs[0] ?? node.outputs[0];
  return (port?.type as Exclude<PinType, "auto">) ?? null;
}
</script>

<template>
  <div class="relative h-full w-full min-h-[70vh] overflow-hidden rounded-lg border border-gray-700 bg-gray-950" data-test="visual-hal-editor">
    <MachineGate label="Visual HAL Editor">
      <div class="relative h-full min-h-[70vh] w-full">
        <!-- Toolbar: refresh (re-fetch + reset to backend truth) + counts -->
        <div class="absolute left-3 top-3 z-20 flex items-center gap-2">
          <button
            class="flex items-center gap-1.5 rounded-md border border-gray-600 bg-gray-800 px-2.5 py-1.5 text-xs font-semibold text-gray-200 hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
            data-test="hal-refresh"
            :disabled="loading"
            title="Re-fetch the HAL layout from the backend — in-session blocks and wires are discarded"
            @click="refresh()"
          >
            <span aria-hidden="true" :class="loading ? 'animate-spin' : ''">↻</span>
            {{ loading ? "Loading…" : "Refresh" }}
          </button>
          <span
            class="rounded border border-gray-700 bg-gray-800/80 px-2 py-1 font-mono text-[11px] text-gray-400"
            data-test="hal-counts"
          >{{ pinCount }} pins · {{ signalCount }} signals</span>
          <span
            v-if="loadError"
            class="flex items-center gap-2 rounded border border-red-800 bg-red-950/60 px-2 py-1 text-xs text-red-300"
            data-test="hal-load-error"
          >
            {{ loadError }}
            <button class="font-semibold underline hover:text-red-200" @click="refresh()">Retry</button>
          </span>
        </div>

        <!-- Empty-state hint — pinned to the viewport, not the (larger) scrollable canvas -->
        <p
          v-if="!loading && !loadError && canvas.nodes.length === 0"
          class="pointer-events-none absolute inset-0 z-10 flex items-center justify-center text-sm text-gray-600 whitespace-nowrap"
        >
          Click the <span class="text-blue-400 font-semibold mx-1">+</span> button to place your first block.
        </p>

        <!-- Scrollable canvas -->
        <div class="absolute inset-0 overflow-auto hal-canvas-bg" @mousedown="onCanvasBackgroundMouseDown">
          <div ref="contentEl" class="relative" :style="canvasSizeStyle">
            <!-- Wires -->
            <svg class="absolute inset-0 pointer-events-none" :width="CANVAS_WIDTH" :height="CANVAS_HEIGHT">
              <path
                v-for="w in wireGeometry"
                :key="w.id"
                :d="w.d"
                fill="none"
                class="stroke-blue-400/70"
                stroke-width="2"
              />
              <path
                v-if="pendingWireGeometry"
                :d="pendingWireGeometry"
                fill="none"
                class="stroke-blue-300"
                stroke-width="2"
                stroke-dasharray="6 4"
              />
            </svg>

            <!-- Wire labels (seeded backend signals) + remove buttons -->
            <template v-for="w in wireGeometry" :key="w.id">
              <span
                v-if="w.label"
                class="pointer-events-none absolute -translate-x-1/2 translate-y-1 z-10 rounded bg-gray-900/80 px-1.5 py-0.5 font-mono text-[10px] text-gray-400"
                :style="{ left: `${w.mid.x}px`, top: `${w.mid.y}px` }"
              >{{ w.label }}</span>
              <button
                class="absolute -translate-x-1/2 -translate-y-1/2 z-10 h-4 w-4 rounded-full bg-gray-800 border border-gray-600 text-gray-400 text-[10px] leading-none hover:bg-red-900 hover:text-red-300 hover:border-red-600"
                :class="w.label ? 'mt-[-14px]' : ''"
                :style="{ left: `${w.mid.x}px`, top: `${w.mid.y}px` }"
                title="Remove wire"
                @click="canvas.removeWire(w.id)"
              >×</button>
            </template>

            <!-- Nodes -->
            <div
              v-for="node in canvas.nodes"
              :key="node.id"
              class="absolute rounded-lg bg-gray-800 border border-gray-700 shadow-lg select-none"
              :style="nodeStyle(node)"
              :data-test-node="node.label"
            >
              <header
                class="flex h-11 items-center justify-between gap-2 rounded-t-lg px-3 text-xs font-semibold uppercase tracking-wide cursor-grab active:cursor-grabbing"
                :class="headerClass(node)"
                @mousedown="onNodeHeaderMouseDown($event, node)"
              >
                <span class="truncate" :title="node.label">{{ node.label }}</span>
                <span
                  v-if="pinNodeType(node)"
                  class="shrink-0 rounded px-1 py-0.5 text-[10px] normal-case font-mono"
                  :class="typeBadgeClass(pinNodeType(node))"
                >{{ pinNodeType(node) }}</span>
                <button class="opacity-70 hover:opacity-100 shrink-0" title="Delete block" @mousedown.stop @click.stop="canvas.removeNode(node.id)">
                  <Icon name="close" class="h-3.5 w-3.5" />
                </button>
              </header>

              <div class="flex justify-between px-2 py-2 gap-2">
                <!-- Inputs -->
                <div class="flex flex-col flex-1 min-w-0">
                  <div
                    v-for="port in node.inputs"
                    :key="port.id"
                    class="flex items-center gap-1.5 h-[30px] px-1 rounded cursor-pointer hover:bg-gray-700/50 min-w-0"
                    :title="portTitle(port)"
                    @click="openInputDrawer(node, port)"
                  >
                    <span :class="portDotClass(port)"></span>
                    <span v-if="port.name" class="text-xs font-mono text-gray-300 shrink-0">{{ port.name }}</span>
                  </div>
                  <button
                    v-if="canvas.canAddInput(node.id)"
                    class="h-[30px] rounded border border-dashed border-gray-600 text-[11px] text-gray-500 hover:text-gray-300 hover:border-gray-400"
                    title="Add input"
                    @mousedown.stop
                    @click.stop="canvas.addInputPort(node.id)"
                  >+ input</button>
                </div>

                <!-- Outputs -->
                <div class="flex flex-col flex-1 min-w-0 items-end">
                  <div
                    v-for="port in node.outputs"
                    :key="port.id"
                    class="flex items-center gap-1.5 h-[30px] px-1 rounded cursor-pointer hover:bg-gray-700/50 min-w-0 justify-end"
                    :title="portTitle(port)"
                    @click="openOutputDrawer(node, port)"
                  >
                    <span v-if="port.name" class="text-xs font-mono text-gray-300 shrink-0">{{ port.name }}</span>
                    <span
                      :class="portDotClass(port)"
                      @mousedown.stop="onOutputDotMouseDown($event, node, port)"
                      @click.stop
                    ></span>
                  </div>
                  <div v-if="canvas.canAddInput(node.id)" class="h-[30px]"></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- FAB -->
        <div class="absolute bottom-6 right-6 z-30 flex flex-col items-end gap-2">
          <Transition
            enter-active-class="transition duration-150 ease-out"
            leave-active-class="transition duration-100 ease-in"
            enter-from-class="opacity-0 translate-y-2"
            leave-to-class="opacity-0 translate-y-2"
          >
            <div v-if="menuOpen" class="rounded-lg border border-gray-700 bg-gray-800 shadow-2xl overflow-hidden w-48" data-test="hal-block-menu">
              <button
                v-for="kind in BLOCK_MENU"
                :key="kind"
                class="flex w-full items-center justify-between gap-2 px-3 py-2 text-sm text-gray-200 hover:bg-gray-700 border-b border-gray-700/60 last:border-b-0"
                :data-test-add-block="kind"
                @click="onAddBlock(kind)"
              >
                <span>{{ BLOCK_DEFINITIONS[kind].label }}</span>
                <span class="text-[10px] uppercase tracking-wide text-gray-500">{{ BLOCK_DEFINITIONS[kind].category }}</span>
              </button>
            </div>
          </Transition>

          <button
            class="h-14 w-14 rounded-full bg-blue-600 hover:bg-blue-500 text-white shadow-2xl flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2 focus:ring-offset-gray-900 transition-transform"
            :class="{ 'rotate-45': menuOpen }"
            data-test="hal-fab"
            title="Add block"
            @click="menuOpen = !menuOpen"
          >
            <Icon name="plus" class="h-7 w-7" />
          </button>
        </div>

        <!-- Left drawer: pick the source (OUT) pin for an input port -->
        <Drawer :open="!!activeInput" side="left" width="w-80" @close="closeInputDrawer">
          <template #header>
            <header v-if="activeInput" class="flex items-center justify-between gap-2 px-4 py-3 border-b border-gray-700">
              <div class="min-w-0">
                <p class="text-xs uppercase tracking-wide text-gray-500">Source for</p>
                <p class="text-sm font-semibold text-gray-100 truncate">{{ activeInput.node.label }} · {{ activeInput.port.name }}</p>
              </div>
              <button class="text-gray-400 hover:text-gray-200" @click="closeInputDrawer">
                <Icon name="close" class="h-4 w-4" />
              </button>
            </header>
          </template>

          <div v-if="activeInput" class="p-3 space-y-2" data-test="hal-input-drawer">
            <input
              v-model="inputSearch"
              type="text"
              placeholder="Filter pins…"
              class="w-full rounded border border-gray-600 bg-gray-900 px-2 py-1.5 font-mono text-sm text-gray-200 placeholder:text-gray-500 focus:border-blue-500 focus:outline-none"
              data-test="hal-input-search"
            />
            <div v-if="inputGateDriver" class="rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-xs text-gray-400">
              Driven from the canvas by <span class="font-mono text-gray-200">{{ inputGateDriver }}</span>.
              <button class="mt-2 block text-red-400 hover:text-red-300" @click="canvas.disconnectPort(activeInput.port.id)">Disconnect</button>
            </div>
            <template v-else>
              <p class="text-xs text-gray-500 px-1">
                Pick a writer pin (OUT) to drive this input — it's placed on the canvas as its own block. Only compatible types are shown.
              </p>
              <button
                v-for="pin in inputDrawerPins"
                :key="pin.id"
                class="flex w-full items-center justify-between gap-2 rounded-md border px-3 py-2 text-left transition-colors"
                :class="canvas.inputSourcePinId(activeInput.port.id) === pin.id
                  ? 'border-green-600 bg-green-950/40'
                  : 'border-gray-700 bg-gray-900 hover:border-gray-500'"
                :title="pin.description"
                @click="onPickSourcePin(pin)"
              >
                <span class="min-w-0">
                  <span class="block text-sm font-mono truncate">{{ pin.fullName }}</span>
                  <span v-if="pin.description || pin.componentName" class="block text-[11px] text-gray-500 truncate">{{ pin.componentName ? pin.componentName + ' · ' : '' }}{{ pin.description }}</span>
                </span>
                <span class="shrink-0 flex items-center gap-1.5">
                  <Icon v-if="canvas.inputSourcePinId(activeInput.port.id) === pin.id" name="check" class="h-3.5 w-3.5 text-green-400" />
                  <span class="rounded px-1.5 py-0.5 text-xs font-mono" :class="typeBadgeClass(pin.type)">{{ pin.type }}</span>
                </span>
              </button>
              <p v-if="inputDrawerPins.length === 0" class="text-xs text-gray-500 px-1 py-4 text-center">No compatible writer pins.</p>
            </template>
          </div>
        </Drawer>

        <!-- Right drawer: pick target (IN) pins for an output port -->
        <Drawer :open="!!activeOutput" side="right" width="w-80" @close="closeOutputDrawer">
          <template #header>
            <header v-if="activeOutput" class="flex items-center justify-between gap-2 px-4 py-3 border-b border-gray-700">
              <div class="min-w-0">
                <p class="text-xs uppercase tracking-wide text-gray-500">Targets for</p>
                <p class="text-sm font-semibold text-gray-100 truncate">{{ activeOutput.node.label }} · {{ activeOutput.port.name }}</p>
              </div>
              <button class="text-gray-400 hover:text-gray-200" @click="closeOutputDrawer">
                <Icon name="close" class="h-4 w-4" />
              </button>
            </header>
          </template>

          <div v-if="activeOutput" class="p-3 space-y-2" data-test="hal-output-drawer">
            <input
              v-model="outputSearch"
              type="text"
              placeholder="Filter pins…"
              class="w-full rounded border border-gray-600 bg-gray-900 px-2 py-1.5 font-mono text-sm text-gray-200 placeholder:text-gray-500 focus:border-blue-500 focus:outline-none"
              data-test="hal-output-search"
            />
            <div v-if="outputWires.length > 0" class="rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-xs text-gray-400 space-y-1">
              <p class="text-gray-500">Chained on the canvas to:</p>
              <div v-for="w in outputWires" :key="w.id" class="flex items-center justify-between gap-2">
                <span class="font-mono text-gray-200">{{ w.label }}</span>
                <button class="text-red-400 hover:text-red-300" @click="canvas.removeWire(w.id)">Remove</button>
              </div>
            </div>

            <p class="text-xs text-gray-500 px-1">
              This output can drive any number of reader pins (IN) — each is placed on the canvas as its own block. Only compatible types are shown.
            </p>
            <button
              v-for="pin in outputDrawerPins"
              :key="pin.id"
              class="flex w-full items-center justify-between gap-2 rounded-md border px-3 py-2 text-left transition-colors"
              :class="canvas.outputTargetPinIds(activeOutput.port.id).includes(pin.id)
                ? 'border-green-600 bg-green-950/40'
                : 'border-gray-700 bg-gray-900 hover:border-gray-500'"
              :title="pin.description"
              @click="onToggleTargetPin(pin)"
            >
              <span class="min-w-0">
                <span class="block text-sm font-mono truncate">{{ pin.fullName }}</span>
                <span v-if="pin.description || pin.componentName" class="block text-[11px] text-gray-500 truncate">{{ pin.componentName ? pin.componentName + ' · ' : '' }}{{ pin.description }}</span>
              </span>
              <span class="shrink-0 flex items-center gap-1.5">
                <Icon
                  v-if="canvas.outputTargetPinIds(activeOutput.port.id).includes(pin.id)"
                  name="check"
                  class="h-3.5 w-3.5 text-green-400"
                />
                <span class="rounded px-1.5 py-0.5 text-xs font-mono" :class="typeBadgeClass(pin.type)">{{ pin.type }}</span>
              </span>
            </button>
            <p v-if="outputDrawerPins.length === 0" class="text-xs text-gray-500 px-1 py-4 text-center">No compatible reader pins.</p>
          </div>
        </Drawer>
      </div>
    </MachineGate>
  </div>
</template>

<style scoped>
.hal-canvas-bg {
  background-image: radial-gradient(circle, rgba(255, 255, 255, 0.06) 1px, transparent 1px);
  background-size: 24px 24px;
}

@keyframes hal-port-shake {
  0%, 100% { transform: translateX(0); }
  20% { transform: translateX(-3px); }
  40% { transform: translateX(3px); }
  60% { transform: translateX(-2px); }
  80% { transform: translateX(2px); }
}
.hal-port-reject {
  animation: hal-port-shake 0.4s ease-in-out;
}
</style>
