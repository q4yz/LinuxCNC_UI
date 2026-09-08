// State + rules engine for the Visual HAL Editor canvas.
//
// Pins come from the real backend (`setPins`, fed by ./loadHalData.ts
// → `GET /api/v1/hal/layout`) and stay fixed/unrenameable — they are
// the "system" side of the world. Signals (named wires between two
// `hal-pin` nodes) are seeded via `seedSignals` from the specific
// `.hal` file being edited, and ARE editable: `renameSignal` renames
// one, `serializeSignals` reads the current signal set back out for
// saving. Only the wiring information is persisted — canvas layout
// (node x/y) is session-local and never sent to the backend. Gate
// blocks placed in-session are frontend-only and are never part of
// what gets saved (see `serializeSignals`).
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

import { reactive, ref } from "vue";
import type { HalFileSignalWrite } from "../../../generated/api";

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

  // Set whenever the operator changes something that would affect a
  // save (renaming/rewiring a signal). Cleared by `clearDirty()`,
  // which the view calls after `reset()` (fresh backend truth) and
  // after a successful save.
  const dirty = ref(false);
  function markDirty(): void {
    dirty.value = true;
  }
  function clearDirty(): void {
    dirty.value = false;
  }

  // The real HAL pin palette, injected by the view once
  // `loadHalLayout()` resolves (see ./loadHalData.ts).
  let pins: HalPin[] = [];

  function setPins(next: HalPin[]): void {
    pins = next;
  }

  function pinsWithDirection(direction: "in" | "out"): HalPin[] {
    return pins.filter((pin) => pin.direction === direction);
  }

  function pinForNode(node: HalNode): HalPin | undefined {
    return node.pinId ? pins.find((p) => p.id === node.pinId) : undefined;
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
      // A "signal" block IS a HAL net, so its label is the net's name
      // and starts empty for the operator to fill in (the header
      // renders an input with a placeholder). Gates keep their fixed
      // type name ("AND", "NOT", …) as a label.
      label: kind === "signal" ? "" : def.label,
      x: pos.x,
      y: pos.y,
      inputs: def.inputNames.map((name) => makePort(id, name, def.portType, "in")),
      outputs: def.outputNames.map((name) => makePort(id, name, def.portType, "out")),
    };
    nodes.push(node);
    return node;
  }

  // Renames a signal block — i.e. the HAL net it stands for. Only
  // "signal" nodes are renameable: gates carry their type name and
  // "hal-pin" nodes carry the real, fixed pin name.
  function renameNode(nodeId: string, label: string): void {
    const node = findNode(nodeId);
    if (!node || node.kind !== "signal") return;
    const next = label.trim();
    if (node.label === next) return;
    node.label = next;
    markDirty();
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
    // A brand-new fan-out wire from a source that already drives a
    // named signal inherits that name — otherwise "add another
    // target to this signal" would silently start a second, unnamed
    // signal from the same source pin.
    const inheritedLabel = label ?? wires.find((w) => w.fromPortId === fromPortId && w.label)?.label;
    wires.push(
      inheritedLabel
        ? { id: nextId("wire"), fromPortId, toPortId, label: inheritedLabel }
        : { id: nextId("wire"), fromPortId, toPortId },
    );
    markDirty();
    return { ok: true };
  }

  function removeWire(wireId: string) {
    const idx = wires.findIndex((w) => w.id === wireId);
    if (idx === -1) return;
    const wire = wires[idx];
    const fromNodeId = findPort(wire.fromPortId)?.node.id;
    const toNodeId = findPort(wire.toPortId)?.node.id;
    wires.splice(idx, 1);
    markDirty();
    if (fromNodeId) pruneOrphanPinNode(fromNodeId);
    if (toNodeId) pruneOrphanPinNode(toNodeId);
  }

  // Renames the whole signal a wire belongs to: every wire sharing
  // the same source port gets the same label, since a HAL signal's
  // name is a property of the source pin's fan-out group, not of one
  // individual wire.
  function renameSignal(fromPortId: string, name: string): void {
    const trimmed = name.trim();
    let changed = false;
    for (const wire of wires) {
      if (wire.fromPortId !== fromPortId) continue;
      const next = trimmed || undefined;
      if (wire.label !== next) {
        wire.label = next;
        changed = true;
      }
    }
    if (changed) markDirty();
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
   * Render each `net` from the file exactly the way the operator
   * builds one by hand: a named **signal block** fed by its source
   * OUT pin and driving every target IN pin. Seeding and hand-wiring
   * therefore produce the same shape, so a saved signal comes back
   * looking (and renaming) like the one that was just drawn.
   *
   * Deterministic grid placement (8 signals per column: source pin
   * left, signal block centre, targets stacked right) — nodes stay
   * draggable afterwards.
   *
   * Returns how many target connections could NOT be drawn (a pin
   * already driven by another net, an unresolvable pin). Those are
   * real HAL conflicts the file already contains; the view surfaces
   * the count so nothing silently disappears on the next save.
   */
  function seedSignals(signals: SeedSignal[]): { incomplete: number } {
    const COLUMN_PITCH = 900;
    const ROW_PITCH = 300;
    const TARGET_PITCH = 70;
    const PER_COLUMN = 8;
    let incomplete = 0;

    signals.forEach((signal, index) => {
      const col = Math.floor(index / PER_COLUMN);
      const row = index % PER_COLUMN;
      const baseX = 100 + col * COLUMN_PITCH;
      const baseY = 100 + row * ROW_PITCH;

      const signalNode = addNode("signal", { x: baseX + 380, y: baseY });
      signalNode.label = signal.name;

      if (signal.source) {
        const sourceNode = getOrCreatePinNode(signal.source, { x: baseX, y: baseY });
        const wired = connectWire(sourceNode.outputs[0]?.id ?? "", signalNode.inputs[0]?.id ?? "");
        if (!wired.ok) incomplete += 1;
      }

      signal.targets.forEach((target, targetIndex) => {
        const targetNode = getOrCreatePinNode(target, {
          x: baseX + 700,
          y: baseY + targetIndex * TARGET_PITCH,
        });
        const wired = connectWire(signalNode.outputs[0]?.id ?? "", targetNode.inputs[0]?.id ?? "");
        if (!wired.ok) incomplete += 1;
      });
    });

    return { incomplete };
  }

  /** Drop every node/wire — used by the view's Refresh, which
   * re-fetches the layout and re-seeds from backend truth. */
  function reset(): void {
    nodes.splice(0, nodes.length);
    wires.splice(0, wires.length);
    placementCounter = 0;
  }

  // --- saving: canvas -> file-write payload -----------------------------

  /** The HAL pin feeding a signal block's input, if a pin drives it. */
  function sourcePinOf(signalNode: HalNode): HalPin | undefined {
    const inputPortId = signalNode.inputs[0]?.id;
    if (!inputPortId) return undefined;
    const wire = wires.find((w) => w.toPortId === inputPortId);
    if (!wire) return undefined;
    const from = findPort(wire.fromPortId);
    // A gate driving the signal is out of scope this pass — only a
    // real pin counts as the net's writer.
    if (!from || from.node.kind !== "hal-pin") return undefined;
    return pinForNode(from.node);
  }

  /** Every HAL pin a signal block's output drives. */
  function targetPinsOf(signalNode: HalNode): HalPin[] {
    const outputPortId = signalNode.outputs[0]?.id;
    if (!outputPortId) return [];
    const pinsOut: HalPin[] = [];
    for (const wire of wires) {
      if (wire.fromPortId !== outputPortId) continue;
      const to = findPort(wire.toPortId);
      if (!to || to.node.kind !== "hal-pin") continue;
      const pin = pinForNode(to.node);
      if (pin) pinsOut.push(pin);
    }
    return pinsOut;
  }

  interface DirectWireGroup {
    sourcePortId: string;
    label?: string;
    sourcePin: HalPin;
    targetPins: HalPin[];
    wireIds: string[];
  }

  /**
   * Connections drawn straight from one pin to another without a
   * signal block, grouped by source port — one net = one writer plus
   * its fan-out. The name lives on the wires themselves.
   */
  function directPinWireGroups(): DirectWireGroup[] {
    const bySource = new Map<string, DirectWireGroup>();
    for (const wire of wires) {
      const from = findPort(wire.fromPortId);
      const to = findPort(wire.toPortId);
      if (!from || !to) continue;
      if (from.node.kind !== "hal-pin" || to.node.kind !== "hal-pin") continue;
      const sourcePin = pinForNode(from.node);
      const targetPin = pinForNode(to.node);
      if (!sourcePin || !targetPin) continue;

      const existing = bySource.get(wire.fromPortId);
      if (existing) {
        existing.targetPins.push(targetPin);
        existing.wireIds.push(wire.id);
        existing.label = existing.label ?? wire.label;
      } else {
        bySource.set(wire.fromPortId, {
          sourcePortId: wire.fromPortId,
          label: wire.label,
          sourcePin,
          targetPins: [targetPin],
          wireIds: [wire.id],
        });
      }
    }
    return [...bySource.values()];
  }

  // --- default names for unnamed nets ------------------------------------

  // LinuxCNC refuses a HAL name longer than HAL_NAME_LEN, so a derived
  // name that would overflow is truncated and given a short hash of the
  // full pin list to keep it unique and stable.
  const HAL_NAME_MAX = 47;

  /** `motion.spindle-on` -> `motion-spindle-on` (HAL-name-safe). */
  function namePart(fullName: string): string {
    return fullName
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "");
  }

  function shortHash(text: string): string {
    let hash = 0;
    for (let i = 0; i < text.length; i += 1) {
      hash = (hash * 31 + text.charCodeAt(i)) | 0;
    }
    return Math.abs(hash).toString(36).slice(0, 4);
  }

  /**
   * Build a net name out of the pins it connects — writer first, then
   * its readers — so an auto-named signal still reads like what it
   * does and can't collide with another net's pins. `taken` carries
   * the names already in use (and gains the one returned).
   */
  function deriveSignalName(pinFullNames: string[], taken: Set<string>): string {
    const base = pinFullNames.map(namePart).filter(Boolean).join("-") || "signal";

    let candidate = base;
    if (candidate.length > HAL_NAME_MAX) {
      const hash = shortHash(base);
      candidate = `${base.slice(0, HAL_NAME_MAX - hash.length - 1)}-${hash}`;
    }

    // Only reachable when two nets touch the same pins in the same
    // order, or when a hand-typed name already claimed this string.
    let unique = candidate;
    let n = 2;
    while (taken.has(unique)) {
      const suffix = `-${n}`;
      unique = `${candidate.slice(0, HAL_NAME_MAX - suffix.length)}${suffix}`;
      n += 1;
    }
    taken.add(unique);
    return unique;
  }

  /**
   * Name every wired-but-unnamed net after the pins it connects, so
   * saving never drops one for lacking a name. Runs just before a
   * save: the generated names land on the canvas too, so what the
   * operator sees is what reaches the file (and stays editable).
   *
   * Returns how many nets were named.
   */
  function autoNameUnnamedSignals(): number {
    const taken = new Set<string>();
    for (const node of nodes) {
      if (node.kind === "signal" && node.label.trim()) taken.add(node.label.trim());
    }
    for (const wire of wires) {
      if (wire.label?.trim()) taken.add(wire.label.trim());
    }

    let named = 0;

    for (const node of nodes) {
      if (node.kind !== "signal" || node.label.trim()) continue;
      const source = sourcePinOf(node);
      const targets = targetPinsOf(node);
      // A block with nothing wired to it isn't a net yet — leave it be.
      if (!source && targets.length === 0) continue;
      const pinNames = [source?.fullName, ...targets.map((p) => p.fullName)].filter(
        (n): n is string => Boolean(n),
      );
      node.label = deriveSignalName(pinNames, taken);
      named += 1;
    }

    for (const group of directPinWireGroups()) {
      if (group.label?.trim()) continue;
      const name = deriveSignalName(
        [group.sourcePin.fullName, ...group.targetPins.map((p) => p.fullName)],
        taken,
      );
      for (const wire of wires) {
        if (group.wireIds.includes(wire.id)) wire.label = name;
      }
      named += 1;
    }

    if (named > 0) markDirty();
    return named;
  }

  /**
   * Read the canvas back out as the payload the backend writes into
   * the `.hal` file. Two shapes count as a net:
   *
   *   1. a **signal block** — the canonical one, and what `seedSignals`
   *      builds — named by its label, fed by one source pin, driving
   *      any number of target pins;
   *   2. a direct **pin -> pin** wire carrying a name on the wire
   *      itself, for connections drawn without a signal block.
   *
   * Anything touching a gate/latch/flip-flop is skipped: gate logic
   * isn't part of what gets saved this pass. A net with no name at
   * all can't be written as a `net` line — `autoNameUnnamedSignals`
   * runs first (on save) so that case doesn't arise in practice.
   */
  function serializeSignals(): HalFileSignalWrite[] {
    const signals: HalFileSignalWrite[] = [];
    const claimedSourcePorts = new Set<string>();

    for (const node of nodes) {
      if (node.kind !== "signal") continue;
      const name = node.label.trim();
      const sourcePin = sourcePinOf(node);
      const targetPins = targetPinsOf(node);
      if (!name || (!sourcePin && targetPins.length === 0)) continue;

      // A pin feeding a signal block is spoken for; don't also emit
      // it as a bare pin -> pin wire below.
      const inputPortId = node.inputs[0]?.id;
      const driver = inputPortId ? wires.find((w) => w.toPortId === inputPortId) : undefined;
      if (driver) claimedSourcePorts.add(driver.fromPortId);

      signals.push({
        name,
        source: sourcePin?.fullName,
        targets: targetPins.map((p) => p.fullName),
      });
    }

    for (const group of directPinWireGroups()) {
      if (claimedSourcePorts.has(group.sourcePortId)) continue;
      const name = group.label?.trim();
      if (!name) continue;
      signals.push({
        name,
        source: group.sourcePin.fullName,
        targets: group.targetPins.map((p) => p.fullName),
      });
    }

    return signals;
  }

  return {
    nodes,
    wires,
    dirty,
    clearDirty,
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
    renameNode,
    renameSignal,
    autoNameUnnamedSignals,
    serializeSignals,
    seedSignals,
    reset,
  };
}
