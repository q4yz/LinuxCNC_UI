// State + rules engine for the Visual HAL Editor canvas.
//
// Pins come from the real backend (`setPins`, fed by ./loadHalData.ts
// → `GET /api/v1/hal/layout`); signals seeded via `seedSignals` render
// the operator's existing HAL wiring as pre-wired pin nodes. Blocks
// placed in-session and any re-wiring are FRONTEND-ONLY state —
// nothing here ever writes back to the backend; a refresh (re-fetch +
// re-seed) resets the canvas to backend truth.
//
// Connection rules enforced here mirror HAL signals:
//   - An input port has at most ONE driver: one incoming `Wire`.
//   - An output port can fan out to any number of outgoing `Wire`s
//     ("one writer, many readers").
//   - Types must match, except the polymorphic "Signal" block whose
//     ports are typed "auto" and adopt whatever concrete type they
//     first touch (resolved dynamically, not stored).
//
// A HAL pin picked from a drawer is not a field tucked onto a port —
// it is placed on the canvas as its own single-port "hal-pin" node,
// wired in exactly like any other block, so the connection is as
// visible as a NOT -> AND chain. `getOrCreatePinNode` is the
// singleton: picking the same pin again reuses that node (and just
// adds another wire to/from it) instead of placing a duplicate.

import { reactive } from "vue";

import { BLOCK_DEFINITIONS } from "./blockDefinitions";
import type { SeedSignal } from "./loadHalData";
import type { BlockKind, HalNode, HalPin, PinType, Port, Wire } from "./types";

let idCounter = 0;
function nextId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${idCounter}`;
}

function makePort(nodeId: string, name: string, type: PinType, direction: "in" | "out"): Port {
  return { id: nextId("port"), nodeId, name, type, direction };
}

export interface ConnectResult {
  ok: boolean;
  message?: string;
}

export function useHalCanvas() {
  const nodes = reactive<HalNode[]>([]);
  const wires = reactive<Wire[]>([]);

  // The real HAL pin palette, injected by the view once
  // `loadHalLayout()` resolves (see ./loadHalData.ts).
  let pins: HalPin[] = [];

  function setPins(next: HalPin[]): void {
    pins = next;
  }

  function pinsWithDirection(direction: "in" | "out"): HalPin[] {
    return pins.filter((pin) => pin.direction === direction);
  }

  let placementCounter = 0;
  function nextPlacement(): { x: number; y: number } {
    const slot = placementCounter % 6;
    placementCounter += 1;
    return { x: 140 + slot * 36, y: 100 + slot * 36 };
  }

  function findNode(nodeId: string): HalNode | undefined {
    return nodes.find((n) => n.id === nodeId);
  }

  function findPort(portId: string): { node: HalNode; port: Port } | null {
    for (const node of nodes) {
      const port = node.inputs.find((p) => p.id === portId) ?? node.outputs.find((p) => p.id === portId);
      if (port) return { node, port };
    }
    return null;
  }

  function findPinNode(pinId: string): HalNode | undefined {
    return nodes.find((n) => n.kind === "hal-pin" && n.pinId === pinId);
  }

  // --- node lifecycle ----------------------------------------------------

  function addNode(kind: BlockKind, at?: { x: number; y: number }): HalNode {
    const def = BLOCK_DEFINITIONS[kind];
    const id = nextId("node");
    const pos = at ?? nextPlacement();
    const node: HalNode = {
      id,
      kind,
      label: def.label,
      x: pos.x,
      y: pos.y,
      inputs: def.inputNames.map((name) => makePort(id, name, def.portType, "in")),
      outputs: def.outputNames.map((name) => makePort(id, name, def.portType, "out")),
    };
    nodes.push(node);
    return node;
  }

  // Singleton lookup-or-create for a HAL pin's stand-in node. A
  // writer (direction "out") pin gets a node with a single OUTPUT
  // port (it drives things); a reader ("in") pin gets a single INPUT
  // port (it consumes a value). `at` only matters on first creation.
  function getOrCreatePinNode(pin: HalPin, at?: { x: number; y: number }): HalNode {
    const existing = findPinNode(pin.id);
    if (existing) return existing;
    const id = nextId("pin-node");
    const pos = at ?? nextPlacement();
    const node: HalNode = {
      id,
      kind: "hal-pin",
      label: pin.fullName,
      x: pos.x,
      y: pos.y,
      pinId: pin.id,
      inputs: pin.direction === "in" ? [makePort(id, "", pin.type, "in")] : [],
      outputs: pin.direction === "out" ? [makePort(id, "", pin.type, "out")] : [],
    };
    nodes.push(node);
    return node;
  }

  function removeNode(nodeId: string) {
    const node = findNode(nodeId);
    if (!node) return;
    const portIds = new Set([...node.inputs.map((p) => p.id), ...node.outputs.map((p) => p.id)]);
    const affectedOtherNodeIds = new Set<string>();
    for (let i = wires.length - 1; i >= 0; i -= 1) {
      const wire = wires[i];
      const touchesFrom = portIds.has(wire.fromPortId);
      const touchesTo = portIds.has(wire.toPortId);
      if (!touchesFrom && !touchesTo) continue;
      const otherPortId = touchesFrom ? wire.toPortId : wire.fromPortId;
      const otherNode = findPort(otherPortId)?.node;
      if (otherNode && otherNode.id !== nodeId) affectedOtherNodeIds.add(otherNode.id);
      wires.splice(i, 1);
    }
    const idx = nodes.findIndex((n) => n.id === nodeId);
    if (idx !== -1) nodes.splice(idx, 1);
    for (const id of affectedOtherNodeIds) pruneOrphanPinNode(id);
  }

  // A "hal-pin" node with no wires left touching its one port is
  // clutter — drop it so re-picking that same pin later places a
  // fresh node instead of pointing at a stale, disconnected one.
  function pruneOrphanPinNode(nodeId: string) {
    const node = findNode(nodeId);
    if (!node || node.kind !== "hal-pin") return;
    const portIds = new Set([...node.inputs.map((p) => p.id), ...node.outputs.map((p) => p.id)]);
    const stillUsed = wires.some((w) => portIds.has(w.fromPortId) || portIds.has(w.toPortId));
    if (!stillUsed) removeNode(nodeId);
  }

  function moveNode(nodeId: string, x: number, y: number) {
    const node = findNode(nodeId);
    if (!node) return;
    node.x = x;
    node.y = y;
  }

  // --- variadic input ports (AND/OR/NAND/NOR/XOR/XNOR) --------------------

  function canAddInput(nodeId: string): boolean {
    const node = findNode(nodeId);
    if (!node) return false;
    const def = BLOCK_DEFINITIONS[node.kind];
    return def.variadicInputs && node.inputs.length < def.maxInputs;
  }

  function canRemoveInput(nodeId: string): boolean {
    const node = findNode(nodeId);
    if (!node) return false;
    const def = BLOCK_DEFINITIONS[node.kind];
    return def.variadicInputs && node.inputs.length > def.minInputs;
  }

  function addInputPort(nodeId: string) {
    const node = findNode(nodeId);
    if (!node || !canAddInput(nodeId)) return;
    const def = BLOCK_DEFINITIONS[node.kind];
    node.inputs.push(makePort(nodeId, `in${node.inputs.length + 1}`, def.portType, "in"));
  }

  function removeLastInputPort(nodeId: string) {
    const node = findNode(nodeId);
    if (!node || !canRemoveInput(nodeId)) return;
    const port = node.inputs[node.inputs.length - 1];
    disconnectPort(port.id);
    node.inputs.pop();
  }

  // --- type resolution -----------------------------------------------------

  function siblingPort(node: HalNode, port: Port): Port | null {
    // Only meaningful for 1-in/1-out "auto"-typed blocks (Signal).
    if (port.direction === "in") return node.outputs[0] ?? null;
    return node.inputs[0] ?? null;
  }

  // Resolves what concrete type a port effectively carries, following
  // a chain of "auto" Signal passthroughs if needed. `seen` guards
  // against a cycle of Signal blocks feeding each other.
  function resolveType(port: Port, seen = new Set<string>()): Exclude<PinType, "auto"> | null {
    if (port.type !== "auto") return port.type;
    if (seen.has(port.id)) return null;
    seen.add(port.id);

    if (port.direction === "out") {
      const wire = wires.find((w) => w.fromPortId === port.id);
      if (wire) {
        const other = findPort(wire.toPortId);
        if (other) return resolveType(other.port, seen);
      }
    } else {
      const wire = wires.find((w) => w.toPortId === port.id);
      if (wire) {
        const other = findPort(wire.fromPortId);
        if (other) return resolveType(other.port, seen);
      }
    }

    const found = findPort(port.id);
    if (found) {
      const sibling = siblingPort(found.node, port);
      if (sibling) return resolveType(sibling, seen);
    }
    return null;
  }

  function typesCompatible(a: Exclude<PinType, "auto"> | null, b: Exclude<PinType, "auto"> | null): boolean {
    if (a === null || b === null) return true;
    return a === b;
  }

  // --- port state queries --------------------------------------------------

  function isInputDriven(portId: string): boolean {
    return wires.some((w) => w.toPortId === portId);
  }

  function isOutputDriving(portId: string): boolean {
    return wires.some((w) => w.fromPortId === portId);
  }

  function inputDriverLabel(portId: string): string | null {
    const wire = wires.find((w) => w.toPortId === portId);
    if (!wire) return null;
    const from = findPort(wire.fromPortId);
    if (!from) return null;
    return from.node.kind === "hal-pin" ? from.node.label : `${from.node.label} · ${from.port.name}`;
  }

  // If `portId` (an input) is currently driven by a HAL-pin node,
  // returns that pin's id — used to highlight the right row as
  // "selected" in the source-picker drawer and to detect "clicking
  // the same pin again" (toggle off) vs. "picking a different one".
  function inputSourcePinId(portId: string): string | null {
    const wire = wires.find((w) => w.toPortId === portId);
    if (!wire) return null;
    const from = findPort(wire.fromPortId);
    return from && from.node.kind === "hal-pin" ? (from.node.pinId ?? null) : null;
  }

  // All HAL pins an output port currently fans out to (via their
  // pin-node), for checkbox highlighting in the target-picker drawer.
  function outputTargetPinIds(portId: string): string[] {
    const ids: string[] = [];
    for (const wire of wires) {
      if (wire.fromPortId !== portId) continue;
      const to = findPort(wire.toPortId);
      if (to && to.node.kind === "hal-pin" && to.node.pinId) ids.push(to.node.pinId);
    }
    return ids;
  }

  // --- HAL pin palette lookups -----------------------------------------------

  function compatibleSourcePins(portId: string): HalPin[] {
    const found = findPort(portId);
    if (!found) return [];
    const wanted = resolveType(found.port);
    const matches = pinsWithDirection("out").filter((pin) => typesCompatible(wanted, pin.type));
    return [...matches].sort((a, b) => a.fullName.localeCompare(b.fullName));
  }

  function compatibleTargetPins(portId: string): HalPin[] {
    const found = findPort(portId);
    if (!found) return [];
    const wanted = resolveType(found.port);
    const matches = pinsWithDirection("in").filter((pin) => typesCompatible(wanted, pin.type));
    return [...matches].sort((a, b) => a.fullName.localeCompare(b.fullName));
  }

  // --- wires (gate-to-gate chaining AND gate-to-HAL-pin) ----------------------

  function connectWire(fromPortId: string, toPortId: string, label?: string): ConnectResult {
    const from = findPort(fromPortId);
    const to = findPort(toPortId);
    if (!from || !to) return { ok: false, message: "Unknown port." };
    if (from.port.direction !== "out" || to.port.direction !== "in") {
      return { ok: false, message: "Wires must run from an output to an input." };
    }
    if (from.node.id === to.node.id) {
      return { ok: false, message: "Cannot wire a block to itself." };
    }
    if (isInputDriven(toPortId)) {
      return { ok: false, message: "That input already has a driver — disconnect it first." };
    }
    const fromType = resolveType(from.port);
    const toType = resolveType(to.port);
    if (!typesCompatible(fromType, toType)) {
      return { ok: false, message: `Type mismatch: ${fromType ?? "auto"} → ${toType ?? "auto"}.` };
    }
    wires.push(label ? { id: nextId("wire"), fromPortId, toPortId, label } : { id: nextId("wire"), fromPortId, toPortId });
    return { ok: true };
  }

  function removeWire(wireId: string) {
    const idx = wires.findIndex((w) => w.id === wireId);
    if (idx === -1) return;
    const wire = wires[idx];
    const fromNodeId = findPort(wire.fromPortId)?.node.id;
    const toNodeId = findPort(wire.toPortId)?.node.id;
    wires.splice(idx, 1);
    if (fromNodeId) pruneOrphanPinNode(fromNodeId);
    if (toNodeId) pruneOrphanPinNode(toNodeId);
  }

  function disconnectPort(portId: string) {
    const touching = wires.filter((w) => w.fromPortId === portId || w.toPortId === portId);
    for (const wire of touching) removeWire(wire.id);
  }

  // Connects `portId` to a real HAL `pin`, placing (or reusing) that
  // pin's singleton node and wiring to/from it depending on which
  // side `portId` is on. `at` is only used the first time the pin is
  // placed. This is the single entry point the drawers call.
  function connectToPin(portId: string, pin: HalPin, at?: { x: number; y: number }): ConnectResult {
    const found = findPort(portId);
    if (!found) return { ok: false, message: "Unknown port." };
    if (found.port.direction === "in" && pin.direction !== "out") {
      return { ok: false, message: `'${pin.fullName}' is a reader, not a writer.` };
    }
    if (found.port.direction === "out" && pin.direction !== "in") {
      return { ok: false, message: `'${pin.fullName}' is a writer, not a reader.` };
    }
    // getOrCreatePinNode may place a brand-new node before we know
    // whether connectWire will actually accept it (e.g. the target
    // is already driven) — prune it back out on failure so a
    // rejected pick never leaves a dangling, unwired block behind.
    const pinNode = getOrCreatePinNode(pin, at);
    const result =
      found.port.direction === "in"
        ? connectWire(pinNode.outputs[0].id, portId)
        : connectWire(portId, pinNode.inputs[0].id);
    if (!result.ok) pruneOrphanPinNode(pinNode.id);
    return result;
  }

  // --- seeding the real backend signals ---------------------------------------

  /**
   * Render the backend's existing signals as pre-wired connections:
   * each signal's source OUT pin node gets a labeled wire to every
   * target IN pin node. Deterministic grid placement (8 signals per
   * column, sources left, targets stacked right) — nodes stay
   * draggable afterwards. Real HAL cannot double-drive an input, but
   * a rejected seed wire is skipped silently rather than surfacing a
   * toast: seeding mirrors backend truth, it doesn't edit it.
   *
   * Signals whose pins were filtered out by the adapter (unknown
   * type tokens) simply don't appear — the canvas always shows the
   * subset it could resolve.
   */
  function seedSignals(signals: SeedSignal[]): void {
    const COLUMN_PITCH = 760;
    const ROW_PITCH = 300;
    const TARGET_PITCH = 70;
    const PER_COLUMN = 8;

    signals.forEach((signal, index) => {
      // A signal with no source OUT pin has nothing to draw — target
      // nodes would sit permanently unwired.
      if (!signal.source) return;
      const col = Math.floor(index / PER_COLUMN);
      const row = index % PER_COLUMN;
      const baseX = 100 + col * COLUMN_PITCH;
      const baseY = 100 + row * ROW_PITCH;

      const sourceNode = getOrCreatePinNode(signal.source, { x: baseX, y: baseY });

      signal.targets.forEach((target, targetIndex) => {
        const targetNode = getOrCreatePinNode(target, {
          x: baseX + 460,
          y: baseY + targetIndex * TARGET_PITCH,
        });
        // Mirroring backend truth: failures (already driven, etc.)
        // are expected no-ops, not user errors.
        connectWire(sourceNode.outputs[0]?.id ?? "", targetNode.inputs[0]?.id ?? "", signal.name);
      });
    });
  }

  /** Drop every node/wire — used by the view's Refresh, which
   * re-fetches the layout and re-seeds from backend truth. */
  function reset(): void {
    nodes.splice(0, nodes.length);
    wires.splice(0, wires.length);
    placementCounter = 0;
  }

  return {
    nodes,
    wires,
    setPins,
    findNode,
    findPort,
    findPinNode,
    addNode,
    removeNode,
    moveNode,
    canAddInput,
    canRemoveInput,
    addInputPort,
    removeLastInputPort,
    resolveType,
    isInputDriven,
    isOutputDriving,
    inputDriverLabel,
    inputSourcePinId,
    outputTargetPinIds,
    compatibleSourcePins,
    compatibleTargetPins,
    connectToPin,
    disconnectPort,
    connectWire,
    removeWire,
    seedSignals,
    reset,
  };
}
