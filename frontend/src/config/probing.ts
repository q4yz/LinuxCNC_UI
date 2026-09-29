// Probing cycle -> macro mapping for ``ProbingPanel.vue``.
//
// Each cycle the panel offers maps onto one ``.ngc`` subroutine in
// ``macros/`` and the positional arguments its ``(Call: ...)`` header
// documents. The panel's own settings (probe diameter, feedrate)
// fill the arguments every cycle shares; anything cycle-specific
// (search distance, boss diameter, ...) is asked for in a dialog —
// ``PROBE_CYCLE_FIELDS`` lists exactly those per cycle + mode.
//
// Directions follow the grid diagram: top = +Y, right = +X.
// Inside (pocket) the probe travels *toward* the wall named by the
// tile; outside (block) it sits beyond that edge and travels back
// toward the part, so every direction flips.

export type ProbeMode = "inside" | "outside";

export type ProbeCycle =
    | "corner-tl" | "edge-top" | "corner-tr"
    | "edge-left" | "edge-right"
    | "corner-bl" | "edge-bottom" | "corner-br"
    | "circle" | "rect";

export interface ProbeField {
  key: string;
  label: string;
  default: number;
  min?: number;
}

export interface ProbeSettings {
  probeDiameter: number;
  feedrate: number;
}

export interface ProbeCall {
  macro: string;
  args: number[];
}

const SEARCH_DIST: ProbeField = {key: "searchDist", label: "Search Distance", default: 10, min: 0.1};
const OVERLAP: ProbeField = {key: "overlap", label: "Edge Overlap (past the corner)", default: 10, min: 0};
const Z_DROP: ProbeField = {key: "zDrop", label: "Z Drop Distance", default: 5, min: 0};
const CLEARANCE: ProbeField = {key: "clearance", label: "Clearance from Edge", default: 5, min: 0.1};

type Dir = 1 | -1;

// Inside-mode (pocket) probe direction per edge tile: [axis 1=X/2=Y, dir].
const EDGE_INSIDE: Record<string, [1 | 2, Dir]> = {
  "edge-top": [2, 1],
  "edge-bottom": [2, -1],
  "edge-left": [1, -1],
  "edge-right": [1, 1],
};

// Inside-mode (pocket) probe directions per corner tile: [xDir, yDir].
const CORNER_INSIDE: Record<string, [Dir, Dir]> = {
  "corner-tl": [-1, 1],
  "corner-tr": [1, 1],
  "corner-bl": [-1, -1],
  "corner-br": [1, -1],
};

function isEdge(cycle: ProbeCycle): boolean {
  return cycle in EDGE_INSIDE;
}

function isCorner(cycle: ProbeCycle): boolean {
  return cycle in CORNER_INSIDE;
}

/** The extra values the dialog asks for, in display order. */
export function probeCycleFields(cycle: ProbeCycle, mode: ProbeMode): ProbeField[] {
  if (isEdge(cycle)) return [SEARCH_DIST];
  // An inside corner starts in the pocket's corner — there is nothing
  // to drive past, so the overlap pre-move is always 0.
  if (isCorner(cycle)) return mode === "outside" ? [SEARCH_DIST, OVERLAP] : [SEARCH_DIST];
  if (cycle === "circle") {
    return mode === "inside"
        ? [{key: "maxRadius", label: "Max Search Radius", default: 15, min: 0.1}]
        : [{key: "bossDiameter", label: "Estimated Boss Diameter", default: 20, min: 0.1}, Z_DROP, CLEARANCE];
  }
  return mode === "inside"
      ? [
        {key: "maxX", label: "Max X Search", default: 20, min: 0.1},
        {key: "maxY", label: "Max Y Search", default: 20, min: 0.1},
      ]
      : [
        {key: "width", label: "Estimated X Width", default: 40, min: 0.1},
        {key: "length", label: "Estimated Y Length", default: 40, min: 0.1},
        Z_DROP,
        CLEARANCE,
      ];
}

/** Human-readable title for the dialog header. */
export function probeCycleTitle(cycle: ProbeCycle, mode: ProbeMode): string {
  const where = mode === "inside" ? "Inside" : "Outside";
  if (cycle === "circle") return mode === "inside" ? "Bore Center (Inside Circle)" : "Boss Center (Outside Circle)";
  if (cycle === "rect") return mode === "inside" ? "Pocket Center (Inside Rectangle)" : "Block Center (Outside Rectangle)";
  const [kind, side] = cycle.split("-");
  const sideName = {tl: "Top-Left", tr: "Top-Right", bl: "Bottom-Left", br: "Bottom-Right"}[side] ?? side[0].toUpperCase() + side.slice(1);
  return `${where} ${sideName} ${kind === "corner" ? "Corner" : "Edge"}`;
}

/**
 * Build the macro name + positional arguments for a cycle. ``values``
 * holds the dialog's answers, keyed by ``ProbeField.key``.
 */
export function buildProbeCall(
    cycle: ProbeCycle,
    mode: ProbeMode,
    settings: ProbeSettings,
    values: Record<string, number>,
): ProbeCall {
  const {probeDiameter, feedrate} = settings;
  const flip = mode === "outside" ? -1 : 1;

  if (isEdge(cycle)) {
    const [axis, dir] = EDGE_INSIDE[cycle];
    // probe_edge: [Axis 1=X/2=Y] [Dir] [Probe Dia] [Search Dist] [Fast Feed]
    return {macro: "probe_edge", args: [axis, dir * flip, probeDiameter, values.searchDist, feedrate]};
  }
  if (isCorner(cycle)) {
    const [xDir, yDir] = CORNER_INSIDE[cycle];
    const overlap = mode === "outside" ? values.overlap : 0;
    // probe_corner: [X Dir] [Y Dir] [Probe Dia] [Search Dist] [Fast Feed] [Edge Overlap]
    return {
      macro: "probe_corner",
      args: [xDir * flip, yDir * flip, probeDiameter, values.searchDist, feedrate, overlap],
    };
  }
  if (cycle === "circle") {
    return mode === "inside"
        // probe_circle_inside: [Probe Dia] [Max Radius] [Fast Feed]
        ? {macro: "probe_circle_inside", args: [probeDiameter, values.maxRadius, feedrate]}
        // probe_circle_outside: [Est Boss Dia] [Z Drop Dist] [Clearance from Edge] [Fast Feed]
        : {macro: "probe_circle_outside", args: [values.bossDiameter, values.zDrop, values.clearance, feedrate]};
  }
  return mode === "inside"
      // probe_rect_inside: [Max X Search] [Max Y Search] [Fast Feed]
      ? {macro: "probe_rect_inside", args: [values.maxX, values.maxY, feedrate]}
      // probe_rect_outside: [Est X Width] [Est Y Length] [Z Drop Dist] [Clearance] [Fast Feed]
      : {macro: "probe_rect_outside", args: [values.width, values.length, values.zDrop, values.clearance, feedrate]};
}
