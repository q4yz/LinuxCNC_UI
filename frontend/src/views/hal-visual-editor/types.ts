// Shared types for the canvas-based Visual HAL Editor concept.
//
// This is a from-scratch prototype UI (node canvas + FAB + side
// drawers) and is intentionally decoupled from the real backend and
// from the older three-column `halVisual` store. Everything here
// operates on mock data so the interaction model can be nailed down
// before any wiring to LinuxCNC HAL happens for real.

export type PinType = "bit" | "float" | "s32" | "u32" | "auto";

export type PortDirection = "in" | "out";

// A pin on a real (external) HAL component — the palettes rendered
// in the left/right drawers. `direction` follows the same
// convention as the old editor: "out" pins *write* a value (drive a
// signal), "in" pins *read* a value (consume a signal).
export interface MockPin {
  id: string;
  fullName: string;
  type: Exclude<PinType, "auto">;
  direction: PortDirection;
  description?: string;
}

// One connector on a node. Inputs can carry at most one driver (one
// incoming `Wire`). Outputs can fan out freely to any number of
// outgoing `Wire`s — mirroring HAL's "one writer, many readers"
// signal rule. Every connection — gate-to-gate chaining *and*
// gate-to-HAL-pin — is a `Wire`; a selected HAL pin is represented
// on the canvas by its own singleton node (see `HalNode.pinId`)
// rather than by a field tucked away on the port.
export interface Port {
  id: string;
  nodeId: string;
  name: string;
  type: PinType;
  direction: PortDirection;
}

export type BlockKind =
  | "signal"
  | "not"
  | "and"
  | "or"
  | "nand"
  | "nor"
  | "xor"
  | "xnor"
  | "sr-latch"
  | "d-flipflop"
  // Placed on the canvas automatically the first time a real HAL pin
  // is picked from a drawer — a single-port stand-in for that pin so
  // the wire to it is visible like any other connection. Never
  // appears in the "+" FAB menu.
  | "hal-pin";

export interface HalNode {
  id: string;
  kind: BlockKind;
  label: string;
  x: number;
  y: number;
  inputs: Port[];
  outputs: Port[];
  // Set only on `kind: "hal-pin"` nodes: which MockPin this node
  // stands in for. Picking the same pin again from a drawer reuses
  // the node with this id instead of placing a duplicate.
  pinId?: string;
}

// A wire: connects one node's output port to another node's input
// port. This is how gates chain together (NOT -> AND -> ...) *and*
// how a gate connects to a real HAL pin (via that pin's node).
export interface Wire {
  id: string;
  fromPortId: string;
  toPortId: string;
}
