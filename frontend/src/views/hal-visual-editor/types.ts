// Shared types for the Visual HAL Editor.
//
// The canvas is a live, read-only view over the real HAL world: pins
// and signals come from `GET /api/v1/hal/layout` (via
// ../..//facades/halFacade.ts, adapted in ./loadHalData.ts). Blocks,
// in-session wires and pin placements are FRONTEND-ONLY state —
// nothing in this editor ever writes back to the backend; a refresh
// resets the canvas to backend truth.

export type PinType = "bit" | "float" | "s32" | "u32" | "auto";

export type PortDirection = "in" | "out";

// A pin on a real (external) HAL component — the palettes rendered
// in the left/right drawers, adapted from the backend's
// `HalPinResource`. `direction` follows HAL semantics: "out" pins
// *write* a value (drive a signal), "in" pins *read* a value
// (consume a signal).
export interface HalPin {
  id: string;
  fullName: string;
  type: Exclude<PinType, "auto">;
  direction: PortDirection;
  /** HAL component that owns the pin (e.g. "parport.0"). */
  componentName?: string;
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
  // Set only on `kind: "hal-pin"` nodes: which HalPin this node
  // stands in for. Picking the same pin again from a drawer reuses
  // the node with this id instead of placing a duplicate.
  pinId?: string;
}

// A wire: connects one node's output port to another node's input
// port. This is how gates chain together (NOT -> AND -> ...) *and*
// how a gate connects to a real HAL pin (via that pin's node).
// `label` is set on wires seeded from a real backend signal (the
// signal's name) so the pre-wired canvas reads like the HAL world it
// mirrors.
export interface Wire {
  id: string;
  fromPortId: string;
  toPortId: string;
  label?: string;
}
