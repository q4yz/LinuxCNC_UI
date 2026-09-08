<script setup lang="ts">
// Visual HAL editor — canvas-based logic wiring board, scoped to one
// `.hal` file.
//
// Opened from a `.hal` file's row in the machine file browser
// (`MachinesExplorer.vue`) as `/hal-editor?file=<path>` — `file` is
// required; pins (live HAL introspection) and that file's `net`
// signals come from `GET /api/v1/hal/layout?file=...`
// (./hal-visual-editor/loadHalData.ts → facades/halFacade.ts). Signals
// are editable (rename, rewire) and Save writes them back into the
// file's delimited signals section — see `useHalCanvas.ts`'s
// `serializeSignals`. Gate blocks placed in-session are frontend-only
// and are never included in what gets saved. Canvas layout (node
// x/y) is session-local and never persisted.
//
// The whole editor is wrapped in MachineGate: HAL pins live on the
// machine backend (:8000), so the offline card shows when the
// machine is down and the layout re-fetches when it comes back.

import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ModalButtonStyle, useConfirm } from "../core/confirm";
import { UNSAVED_PROMPT, useUnsavedChangesGuard } from "../router/guards/unsavedChangesGuard";
import { useConsoleStore } from "../stores/console";
import { BaseButton, Drawer, Icon } from "../ui/index.ts";
import MachineGate from "../components/machine/MachineGate.vue";
import { useMachineOnline } from "../composables/useMachineOnline";
import { useToast } from "../core/toast";
import HalVisualService from "../facades/halFacade";
import { closeToPrevious } from "../helpers/closeToPrevious";
import { BLOCK_DEFINITIONS, BLOCK_MENU } from "./hal-visual-editor/blockDefinitions";
import { nodeHeight, portAnchor, NODE_WIDTH } from "./hal-visual-editor/layout";
import { loadHalLayout } from "./hal-visual-editor/loadHalData";
import { useHalCanvas } from "./hal-visual-editor/useHalCanvas";
import type { BlockKind, HalNode, HalPin, PinType, Port } from "./hal-visual-editor/types";

const canvas = useHalCanvas();
const toast = useToast();
const consoleStore = useConsoleStore();
const route = useRoute();
const router = useRouter();
const { isMachineOnline } = useMachineOnline();

// --- target file (required) --------------------------------------------------

const file = computed(() => {
  const raw = route.query.file;
  return typeof raw === "string" && raw ? raw : null;
});
const hasValidTarget = computed(() => file.value !== null);

// --- layout loading -----------------------------------------------------------

const loading = ref(false);
const saving = ref(false);
const loadError = ref<string | null>(null);
const pinCount = ref(0);
const signalCount = ref(0);

async function refresh(): Promise<void> {
  if (loading.value || !file.value) return;
  loading.value = true;
  loadError.value = null;
  try {
    const data = await loadHalLayout(file.value);
    if (!data) {
      loadError.value = "Failed to load the HAL layout from the backend.";
      return;
    }
    // Reset to backend truth: in-session blocks/wires are discarded.
    canvas.reset();
    canvas.setPins(data.pins);
    const { incomplete } = canvas.seedSignals(data.signals);
    canvas.clearDirty();
    pinCount.value = data.pins.length;
    signalCount.value = data.signals.length;
    if (incomplete > 0) {
      // The file drives the same pin from more than one net (or names
      // a pin that can't be resolved). The canvas can't show it, so
      // saving would drop it — say so instead of losing it quietly.
      consoleStore.warning(
        `${incomplete} connection(s) in '${file.value}' could not be drawn (a pin is already driven by another net). Saving will drop them.`,
        { popup: true },
      );
    }
  } finally {
    loading.value = false;
  }
}

async function confirmDiscardIfDirty(): Promise<boolean> {
  if (!canvas.dirty.value) return true;
  return useConfirm({
    title: UNSAVED_PROMPT.title,
    question: UNSAVED_PROMPT.question,
    confirmButtonText: UNSAVED_PROMPT.confirmText,
    confirmButtonStyle: ModalButtonStyle.DANGER,
    rejectButtonText: UNSAVED_PROMPT.rejectText,
    rejectButtonStyle: ModalButtonStyle.SECONDARY,
    showDismissCrossButton: false,
  });
}

async function onRefreshClick(): Promise<void> {
  if (!(await confirmDiscardIfDirty())) return;
  await refresh();
}

// --- save / close --------------------------------------------------------------

async function saveEditor(): Promise<void> {
  if (!file.value || saving.value) return;
  saving.value = true;
  try {
    // A net with no name can't be written as a `net` line. Rather
    // than dropping it, name it after the pins it connects — the
    // names land on the canvas first, so what the operator sees is
    // what reaches the file.
    const autoNamed = canvas.autoNameUnnamedSignals();

    const result = await HalVisualService.saveLayout(file.value, canvas.serializeSignals());
    if (!result) {
      consoleStore.error(`Failed to save '${file.value}'.`, { popup: true });
      return;
    }
    // Re-seed from the freshly-written file so the canvas reflects
    // exactly what landed on disk (backend truth, same as Refresh).
    await refresh();
    consoleStore.success(`File '${file.value}' saved successfully!`, { popup: true });
    if (autoNamed > 0) {
      consoleStore.info(
        `${autoNamed} unnamed signal(s) were named after the pins they connect. Rename them any time.`,
        { popup: true },
      );
    }
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    consoleStore.error(`Failed to save file: ${detail}`, { popup: true });
  } finally {
    saving.value = false;
  }
}

async function saveAndCloseEditor(): Promise<void> {
  await saveEditor();
  closeEditor();
}

async function confirmClose(): Promise<void> {
  if (await confirmDiscardIfDirty()) closeEditor();
}

function closeEditor(): void {
  // The caller already settled any unsaved work (confirmClose prompts,
  // saveAndClose persists). Clearing the flag first keeps the
  // route-leave guard from asking a second time on the way out.
  canvas.clearDirty();
  // Step back so the machine file browser keeps the folder it was on
  // (it lives in the URL); fall back to Config when the editor was
  // opened directly.
  closeToPrevious(router, "config");
}

useUnsavedChangesGuard(() => canvas.dirty.value);

function onSaveShortcut(event: KeyboardEvent): void {
  const isSaveChord = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s";
  if (!isSaveChord) return;
  event.preventDefault();
  if (!canvas.dirty.value) return;
  void saveEditor();
}

onMounted(() => {
  if (isMachineOnline.value) void refresh();
  document.addEventListener("keydown", onSaveShortcut);
});

onBeforeUnmount(() => {
  document.removeEventListener("keydown", onSaveShortcut);
});

// The gate unmounts the editor while the machine is offline; when it
// comes back online, pull a fresh layout.
watch(isMachineOnline, (next) => {
  if (next) void refresh();
});

// Vue Router reuses this component when only the query changes (same
// route name) — e.g. navigating from one .hal file's editor straight
// to another's. `onMounted` alone would miss that; this watcher picks
// it up. Guarded by the same unsaved-changes confirm as Refresh/Close,
// reverting the URL on decline so the canvas and address bar agree.
watch(file, async (next, prev) => {
  if (next === prev) return;
  if (!(await confirmDiscardIfDirty())) {
    if (prev) void router.replace({ name: "hal-editor", query: { file: prev } });
    return;
  }
  await refresh();
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
  fromPortId: string;
  d: string;
  mid: { x: number; y: number };
  label?: string;
  // Both endpoints are real HAL pins — a "signal" wire whose label is
  // the editable, savable signal name. A wire touching a gate/latch
  // block keeps its label read-only (gates aren't part of what saves).
  isSignal: boolean;
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
        fromPortId: wire.fromPortId,
        d: bezierPath(fromAnchor, toAnchor),
        mid: { x: (fromAnchor.x + toAnchor.x) / 2, y: (fromAnchor.y + toAnchor.y) / 2 },
        isSignal: from.node.kind === "hal-pin" && to.node.kind === "hal-pin",
        ...(wire.label ? { label: wire.label } : {}),
      },
    ];
  });
});

function onSignalNameChange(w: WireGeometry, event: Event): void {
  const value = (event.target as HTMLInputElement).value;
  canvas.renameSignal(w.fromPortId, value);
}

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
  <div v-if="!hasValidTarget" class="flex h-full min-h-[70vh] w-full items-center justify-center text-sm text-gray-500">
    Open a <span class="mx-1 font-mono text-gray-300">.hal</span> file from a machine's file browser (Config → Machines) to use the Visual HAL Editor.
  </div>
  <div v-else class="flex h-full min-h-[70vh] w-full flex-col overflow-hidden rounded-lg border border-gray-700 bg-gray-950" data-test="visual-hal-editor">
    <!-- Header: filename + Save / Save & Close / Close, mirroring EditorView.vue -->
    <div class="flex items-center justify-between border-b border-gray-700 bg-gray-800 px-4 py-3">
      <span class="truncate font-mono text-blue-300" :title="file ?? undefined">Editing {{ file }} (Visual HAL Editor)</span>
      <div class="flex gap-2">
        <BaseButton variant="primary" :disabled="saving" @click="saveAndCloseEditor">Save &amp; Close</BaseButton>
        <BaseButton variant="success" :disabled="saving || !canvas.dirty.value" @click="saveEditor">Save</BaseButton>
        <BaseButton variant="secondary" class="mr-30" @click="confirmClose">Close</BaseButton>
      </div>
    </div>

    <div class="relative min-h-0 flex-1">
    <MachineGate label="Visual HAL Editor">
      <div class="relative h-full min-h-[70vh] w-full">
        <!-- Toolbar: refresh (re-fetch + reset to backend truth) + counts -->
        <div class="absolute left-3 top-3 z-20 flex items-center gap-2">
          <button
            class="flex items-center gap-1.5 rounded-md border border-gray-600 bg-gray-800 px-2.5 py-1.5 text-xs font-semibold text-gray-200 hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
            data-test="hal-refresh"
            :disabled="loading"
            title="Re-fetch the HAL layout from the backend — in-session blocks and wires are discarded"
            @click="onRefreshClick()"
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

            <!-- Wire labels: editable signal name for hal-pin <-> hal-pin
                 wires (this is what gets saved), read-only for wires
                 touching a gate/latch block. -->
            <template v-for="w in wireGeometry" :key="w.id">
              <input
                v-if="w.isSignal"
                :value="w.label ?? ''"
                placeholder="named on save"
                class="pointer-events-auto absolute z-10 -translate-x-1/2 translate-y-1 rounded border border-gray-700 bg-gray-900/90 px-1.5 py-0.5 text-center font-mono text-[10px] text-gray-200 placeholder:text-gray-500 focus:border-blue-500 focus:outline-none"
                style="width: 132px"
                :style="{ left: `${w.mid.x}px`, top: `${w.mid.y}px` }"
                :title="w.label ? `Signal name: ${w.label}` : 'Left empty, this signal is named after the pins it connects when you save'"
                data-test="hal-signal-name"
                @mousedown.stop
                @change="onSignalNameChange(w, $event)"
              />
              <span
                v-else-if="w.label"
                class="pointer-events-none absolute -translate-x-1/2 translate-y-1 z-10 rounded bg-gray-900/80 px-1.5 py-0.5 font-mono text-[10px] text-gray-400"
                :style="{ left: `${w.mid.x}px`, top: `${w.mid.y}px` }"
              >{{ w.label }}</span>
              <button
                class="absolute -translate-x-1/2 -translate-y-1/2 z-10 h-4 w-4 rounded-full bg-gray-800 border border-gray-600 text-gray-400 text-[10px] leading-none hover:bg-red-900 hover:text-red-300 hover:border-red-600"
                :class="w.label || w.isSignal ? 'mt-[-14px]' : ''"
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
                <!-- A signal block IS a HAL net: its label is the net
                     name and is edited in place. Pins and gates keep a
                     fixed, read-only label. -->
                <input
                  v-if="node.kind === 'signal'"
                  :value="node.label"
                  placeholder="named on save"
                  class="min-w-0 flex-1 rounded border border-gray-600 bg-gray-900/70 px-1.5 py-0.5 font-mono text-[11px] normal-case tracking-normal text-gray-100 placeholder:text-gray-500 focus:border-blue-500 focus:outline-none"
                  :title="node.label ? `Signal name: ${node.label}` : 'Left empty, this signal is named after the pins it connects when you save'"
                  data-test="hal-signal-block-name"
                  @mousedown.stop
                  @change="canvas.renameNode(node.id, ($event.target as HTMLInputElement).value)"
                />
                <span v-else class="truncate" :title="node.label">{{ node.label }}</span>
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
