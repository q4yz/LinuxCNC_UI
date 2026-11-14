// Page layouts (Settings -> Page layout): which panels the Dashboard and
// the Running page show, in which column, in which order.
//
// Plain data + pure functions (no .vue imports) so the tests load it
// directly; ``PageLayout.vue`` maps the ids to the components.

export type PageId = "dashboard" | "running";
export type Column = "left" | "right";
export type Placement = Column | "hidden";

export interface PageLayout {
  left: string[];
  right: string[];
  hidden: string[];
}

export interface PanelDef {
  id: string;
  label: string;
  /** ``MachineGate`` label: the panel only mounts while the machine backend
   * is reachable. ``null``: never gated (the console explains "offline"). */
  gate: string | null;
}

/** Every panel a page can show. */
export const PANELS: readonly PanelDef[] = Object.freeze([
  { id: "machine", label: "Machine (power)", gate: "Machine" },
  { id: "dro", label: "DRO", gate: "DRO" },
  { id: "jog", label: "Jog controls", gate: "Jog" },
  { id: "tools", label: "Tools", gate: "Tools" },
  { id: "temperature", label: "Temperatures", gate: "Temperature" },
  { id: "io", label: "I/O", gate: "I/O" },
  { id: "leds", label: "LEDs", gate: "LEDs" },
  { id: "job", label: "Job status", gate: "Job status" },
  { id: "axis_speed", label: "Axis speed", gate: "Axis speed" },
  { id: "console", label: "Console", gate: null },
  { id: "camera", label: "Camera", gate: "Camera" },
  { id: "macros", label: "Macros & NGC", gate: "Macros" },
  { id: "mcodes", label: "M-Codes", gate: "M-Codes" },
]);

export const PANEL_IDS: readonly string[] = Object.freeze(PANELS.map((p) => p.id));

export function panelDef(id: string): PanelDef | undefined {
  return PANELS.find((p) => p.id === id);
}

function layout(left: string[], right: string[]): PageLayout {
  return { left, right, hidden: PANEL_IDS.filter((id) => !left.includes(id) && !right.includes(id)) };
}

/** What each page showed before the layout was configurable. */
export const DEFAULT_LAYOUTS: Readonly<Record<PageId, PageLayout>> = Object.freeze({
  dashboard: layout(["machine", "dro", "jog", "tools", "temperature", "io", "leds"], ["job", "console", "camera"]),
  running: layout(["job", "axis_speed"], ["tools"]),
});

/** Column widths (flex ratio left : right) per page. */
export const COLUMN_RATIO: Readonly<Record<PageId, [number, number]>> = Object.freeze({
  dashboard: [1, 2],
  running: [6, 5],
});

const PLACEMENTS: readonly Placement[] = ["left", "right", "hidden"];

/**
 * A stored layout, cleaned: unknown ids and duplicates dropped (the first
 * place an id appears wins), and a panel the stored value does not
 * mention (one added in a later version) placed as in ``fallback``.
 * ``undefined`` for a value that is not a layout at all.
 */
export function normaliseLayout(raw: unknown, fallback: PageLayout): PageLayout | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const source = raw as Record<string, unknown>;
  if (!PLACEMENTS.some((p) => Array.isArray(source[p]))) return undefined;
  const seen = new Set<string>();
  const out: PageLayout = { left: [], right: [], hidden: [] };
  for (const place of PLACEMENTS) {
    const list = Array.isArray(source[place]) ? (source[place] as unknown[]) : [];
    for (const id of list) {
      if (typeof id !== "string" || !PANEL_IDS.includes(id) || seen.has(id)) continue;
      seen.add(id);
      out[place].push(id);
    }
  }
  for (const place of PLACEMENTS) {
    for (const id of fallback[place]) {
      if (!seen.has(id) && PANEL_IDS.includes(id)) {
        seen.add(id);
        out[place].push(id);
      }
    }
  }
  return out;
}

export function placementOf(value: PageLayout, id: string): Placement {
  return PLACEMENTS.find((p) => value[p].includes(id)) ?? "hidden";
}

/** ``id`` moved to the end of ``to`` (a new layout; ``value`` untouched). */
export function movePanel(value: PageLayout, id: string, to: Placement): PageLayout {
  const next: PageLayout = {
    left: value.left.filter((p) => p !== id),
    right: value.right.filter((p) => p !== id),
    hidden: value.hidden.filter((p) => p !== id),
  };
  next[to].push(id);
  return next;
}

/** ``id`` one place up (``-1``) or down (``+1``) within its column. */
export function shiftPanel(value: PageLayout, id: string, delta: -1 | 1): PageLayout {
  const place = placementOf(value, id);
  const list = [...value[place]];
  const from = list.indexOf(id);
  const to = from + delta;
  if (from < 0 || to < 0 || to >= list.length) return value;
  [list[from], list[to]] = [list[to], list[from]];
  return { ...value, [place]: list };
}
