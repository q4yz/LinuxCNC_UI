// Block palette metadata for the Visual HAL Editor concept canvas.
//
// Each entry describes one item in the "+" FAB menu: its ports, the
// pin type those ports carry, and whether the input count is
// variadic (logic gates support 2-8 inputs, matching LinuxCNC's
// `and2`/`and3`/... component family conceptually). Memory blocks
// (latches / flip-flops) demonstrate the asymmetric-I/O case: named
// ports instead of generic in1/in2, and inputs/outputs that don't
// mirror each other 1:1.

import type { BlockKind, PinType } from "./types";

export interface BlockDefinition {
  kind: BlockKind;
  label: string;
  shortLabel: string;
  category: "signal" | "gate" | "memory" | "pin";
  description: string;
  // Fixed-type ports carry this type. "auto" (signal only) means
  // the port adopts whatever concrete type it first connects to.
  portType: PinType;
  variadicInputs: boolean;
  minInputs: number;
  maxInputs: number;
  // Starting input port names. For variadic gates this is the
  // initial set (in1, in2); more can be appended up to maxInputs.
  inputNames: string[];
  outputNames: string[];
}

function numberedInputs(count: number): string[] {
  return Array.from({ length: count }, (_, i) => `in${i + 1}`);
}

export const BLOCK_DEFINITIONS: Record<BlockKind, BlockDefinition> = {
  signal: {
    kind: "signal",
    label: "Signal",
    shortLabel: "SIG",
    category: "signal",
    description: "Direct connection — passes its input straight through to its output.",
    portType: "auto",
    variadicInputs: false,
    minInputs: 1,
    maxInputs: 1,
    inputNames: ["in"],
    outputNames: ["out"],
  },
  not: {
    kind: "not",
    label: "NOT",
    shortLabel: "NOT",
    category: "gate",
    description: "Inverts a single bit input.",
    portType: "bit",
    variadicInputs: false,
    minInputs: 1,
    maxInputs: 1,
    inputNames: ["in"],
    outputNames: ["out"],
  },
  and: {
    kind: "and",
    label: "AND",
    shortLabel: "AND",
    category: "gate",
    description: "Output is true only when every input is true.",
    portType: "bit",
    variadicInputs: true,
    minInputs: 2,
    maxInputs: 8,
    inputNames: numberedInputs(2),
    outputNames: ["out"],
  },
  or: {
    kind: "or",
    label: "OR",
    shortLabel: "OR",
    category: "gate",
    description: "Output is true when any input is true.",
    portType: "bit",
    variadicInputs: true,
    minInputs: 2,
    maxInputs: 8,
    inputNames: numberedInputs(2),
    outputNames: ["out"],
  },
  nand: {
    kind: "nand",
    label: "NAND",
    shortLabel: "NAND",
    category: "gate",
    description: "Inverted AND.",
    portType: "bit",
    variadicInputs: true,
    minInputs: 2,
    maxInputs: 8,
    inputNames: numberedInputs(2),
    outputNames: ["out"],
  },
  nor: {
    kind: "nor",
    label: "NOR",
    shortLabel: "NOR",
    category: "gate",
    description: "Inverted OR.",
    portType: "bit",
    variadicInputs: true,
    minInputs: 2,
    maxInputs: 8,
    inputNames: numberedInputs(2),
    outputNames: ["out"],
  },
  xor: {
    kind: "xor",
    label: "XOR",
    shortLabel: "XOR",
    category: "gate",
    description: "Output is true when an odd number of inputs are true.",
    portType: "bit",
    variadicInputs: true,
    minInputs: 2,
    maxInputs: 8,
    inputNames: numberedInputs(2),
    outputNames: ["out"],
  },
  xnor: {
    kind: "xnor",
    label: "XNOR",
    shortLabel: "XNOR",
    category: "gate",
    description: "Inverted XOR.",
    portType: "bit",
    variadicInputs: true,
    minInputs: 2,
    maxInputs: 8,
    inputNames: numberedInputs(2),
    outputNames: ["out"],
  },
  "sr-latch": {
    kind: "sr-latch",
    label: "SR Latch",
    shortLabel: "SR",
    category: "memory",
    description: "Set/Reset latch — asymmetric I/O: 2 inputs (S, R), 2 outputs (Q, /Q).",
    portType: "bit",
    variadicInputs: false,
    minInputs: 2,
    maxInputs: 2,
    inputNames: ["S", "R"],
    outputNames: ["Q", "/Q"],
  },
  "d-flipflop": {
    kind: "d-flipflop",
    label: "D Flip-Flop",
    shortLabel: "D-FF",
    category: "memory",
    description: "Clocked D flip-flop — 2 inputs (D, CLK), 2 outputs (Q, /Q).",
    portType: "bit",
    variadicInputs: false,
    minInputs: 2,
    maxInputs: 2,
    inputNames: ["D", "CLK"],
    outputNames: ["Q", "/Q"],
  },
  // Not placed via the FAB — created (as a singleton per MockPin) by
  // useHalCanvas.getOrCreatePinNode when a pin is picked from a
  // drawer. Its actual ports are built dynamically from the picked
  // MockPin's type/direction, not from inputNames/outputNames below.
  "hal-pin": {
    kind: "hal-pin",
    label: "HAL Pin",
    shortLabel: "PIN",
    category: "pin",
    description: "Stand-in for a real HAL pin selected from a drawer.",
    portType: "bit",
    variadicInputs: false,
    minInputs: 1,
    maxInputs: 1,
    inputNames: [],
    outputNames: [],
  },
};

// Menu order for the FAB dropdown.
export const BLOCK_MENU: BlockKind[] = [
  "signal",
  "not",
  "and",
  "or",
  "nand",
  "nor",
  "xor",
  "xnor",
  "sr-latch",
  "d-flipflop",
];
