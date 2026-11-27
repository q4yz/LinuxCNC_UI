// Page layouts (Settings -> Page layout): which panels the Dashboard and
// the Running page show, in which column, in which order.
//
// Plain data + pure functions (no .vue imports) so the tests load it
// directly; ``PageLayout.vue`` maps the ids to the components.

export type PageId = "dashboard" | "running";
/** 1, 2 or 3 columns. */
export type ColumnCount = 1 | 2 | 3;
export const COLUMN_COUNTS: readonly ColumnCount[] = [1, 2, 3];
/** Column widths are twelfths, like a browser grid. */
export const GRID = 12;
/** A column narrower than this does not fit: the page uses fewer columns
 * (or, when no enabled layout fits, wraps them one below the other). */
export const MIN_COLUMN_PX = 420;

/** One placed panel; ``uid`` tells two of the same panel apart. */
export interface PanelItem {
  uid: string;
  panel: string;
}

export interface ColumnLayout {
  enabled: boolean;
  /** Twelfths per column, summing to 12. */
  widths: number[];
  columns: PanelItem[][];
}

/** A page's layouts: index 0 = one column, 1 = two, 2 = three. */
export interface PageLayout {
  version: 2;
  layouts: ColumnLayout[];
}

/** The layout format before 1 / 2 / 3 columns (migrated on load). */
interface LegacyLayout {
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
  { id: "probe", label: "Probing", gate: "Probing" },
  { id: "tools", label: "Tools", gate: "Tools" },
  { id: "temperature", label: "Temperatures", gate: "Temperature" },
  { id: "io", label: "I/O", gate: "I/O" },
  { id: "leds", label: "LEDs", gate: "LEDs" },
  { id: "ace", label: "ACE Pro (filament)", gate: "ACE" },
  { id: "job", label: "Job status", gate: "Job status" },
  { id: "axis_speed", label: "Tuning (speed, Z offset, flow)", gate: "Tuning" },
  { id: "console", label: "Console", gate: null },
  { id: "camera", label: "Camera", gate: "Camera" },
  { id: "macros", label: "Macros & NGC", gate: "Macros" },
  { id: "mcodes", label: "M-Codes", gate: "M-Codes" },
]);

export const PANEL_IDS: readonly string[] = Object.freeze(PANELS.map((p) => p.id));

export function panelDef(id: string): PanelDef | undefined {
  return PANELS.find((p) => p.id === id);
}

let uidCounter = 0;

/** A new item id (unique within a page). */
export function newUid(): string {
  uidCounter += 1;
  return `${Date.now().toString(36)}${uidCounter.toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

const items = (ids: string[]): PanelItem[] => ids.map((panel, k) => ({ uid: `${panel}-${k}`, panel }));

function pageLayout(one: string[], two: [string[], string[], [number, number]],
                    three: [string[], string[], string[], [number, number, number]], threeEnabled = false): PageLayout {
  return {
    version: 2,
    layouts: [
      { enabled: true, widths: [GRID], columns: [items(one)] },
      { enabled: true, widths: [...two[2]], columns: [items(two[0]), items(two[1])] },
      { enabled: threeEnabled, widths: [...three[3]], columns: [items(three[0]), items(three[1]), items(three[2])] },
    ],
  };
}

const DASH_LEFT = ["machine", "dro", "jog", "probe", "tools", "temperature", "io", "leds"];
const DASH_RIGHT = ["job", "console", "camera"];

/** What each page showed before (two columns), one column = both in a row,
 * three columns ready but off. */
export const DEFAULT_LAYOUTS: Readonly<Record<PageId, PageLayout>> = Object.freeze({
  dashboard: pageLayout(
    [...DASH_LEFT, ...DASH_RIGHT],
    [DASH_LEFT, DASH_RIGHT, [4, 8]],
    [["machine", "dro", "jog", "probe"], ["job", "console", "camera"], ["tools", "temperature", "io", "leds"], [3, 6, 3]],
  ),
  running: pageLayout(
    ["job", "axis_speed", "tools", "ace"],
    [["job", "axis_speed"], ["tools", "ace"], [7, 5]],
    [["job"], ["axis_speed"], ["tools", "ace"], [4, 4, 4]],
  ),
});

const clone = (value: PageLayout): PageLayout => JSON.parse(JSON.stringify(value));

function cleanWidths(raw: unknown, n: number, fallback: number[]): number[] {
  if (!Array.isArray(raw) || raw.length !== n) return [...fallback];
  const widths = raw.map((w) => Math.round(Number(w)));
  if (widths.some((w) => !Number.isFinite(w) || w < 1) || widths.reduce((a, b) => a + b, 0) !== GRID) return [...fallback];
  return widths;
}

/**
 * A stored layout, cleaned: unknown panels dropped, a repeated item id
 * renewed, bad widths replaced by the default's, at least one layout on.
 * The earlier format (``left`` / ``right`` / ``hidden``) becomes the two
 * column layout, its one column version both in a row, three columns off.
 * ``undefined`` for a value that is not a layout at all.
 */
export function normaliseLayout(raw: unknown, fallback: PageLayout): PageLayout | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const source = raw as Record<string, unknown>;
  if (source.version !== 2) {
    const legacy = normaliseLegacy(source, fallback);
    return legacy ? fromLegacy(legacy, fallback) : undefined;
  }
  if (!Array.isArray(source.layouts) || source.layouts.length !== 3) return undefined;
  const seen = new Set<string>();
  const layouts = COLUMN_COUNTS.map((n, k): ColumnLayout => {
    const given = (source.layouts as unknown[])[k];
    const base = fallback.layouts[k];
    const entry = given && typeof given === "object" ? (given as Record<string, unknown>) : {};
    const columns = Array.from({ length: n }, (_, c) => {
      const list = Array.isArray(entry.columns) && Array.isArray(entry.columns[c]) ? (entry.columns[c] as unknown[]) : [];
      const out: PanelItem[] = [];
      for (const item of list) {
        const record = item && typeof item === "object" ? (item as Record<string, unknown>) : null;
        const panel = typeof record?.panel === "string" ? record.panel : typeof item === "string" ? item : null;
        if (!panel || !PANEL_IDS.includes(panel)) continue;
        let uid = typeof record?.uid === "string" && record.uid ? record.uid : newUid();
        if (seen.has(`${k}:${uid}`)) uid = newUid();
        seen.add(`${k}:${uid}`);
        out.push({ uid, panel });
      }
      return out;
    });
    return {
      enabled: typeof entry.enabled === "boolean" ? entry.enabled : base.enabled,
      widths: cleanWidths(entry.widths, n, base.widths),
      columns,
    };
  });
  if (!layouts.some((l) => l.enabled)) layouts[0].enabled = true;
  return { version: 2, layouts };
}

function normaliseLegacy(source: Record<string, unknown>, fallback: PageLayout): LegacyLayout | undefined {
  const places = ["left", "right", "hidden"] as const;
  if (!places.some((p) => Array.isArray(source[p]))) return undefined;
  const seen = new Set<string>();
  const out: LegacyLayout = { left: [], right: [], hidden: [] };
  for (const place of places) {
    for (const id of Array.isArray(source[place]) ? (source[place] as unknown[]) : []) {
      if (typeof id !== "string" || !PANEL_IDS.includes(id) || seen.has(id)) continue;
      seen.add(id);
      out[place].push(id);
    }
  }
  // a panel the old value did not know (added since): where the default has it
  const [left, right] = fallback.layouts[1].columns.map((col) => col.map((i) => i.panel));
  for (const id of PANEL_IDS) {
    if (seen.has(id)) continue;
    if (left.includes(id)) out.left.push(id);
    else if (right.includes(id)) out.right.push(id);
  }
  return out;
}

function fromLegacy(old: LegacyLayout, fallback: PageLayout): PageLayout {
  const value = clone(fallback);
  value.layouts[0].columns = [items([...old.left, ...old.right])];
  value.layouts[1].columns = [items(old.left), items(old.right)];
  return value;
}

// -- editing (each returns a new value; the given one stays as it is) ------- //

/** ``panel`` at the end of the first column of the ``n``-column layout. */
export function addPanel(value: PageLayout, n: ColumnCount, panel: string): PageLayout {
  const next = clone(value);
  next.layouts[n - 1].columns[0].push({ uid: newUid(), panel });
  return next;
}

/** The item ``uid`` to ``column`` at ``index`` (its place counted without it). */
export function moveItem(value: PageLayout, n: ColumnCount, uid: string, column: number, index: number): PageLayout {
  const next = clone(value);
  const layout = next.layouts[n - 1];
  let item: PanelItem | undefined;
  for (const col of layout.columns) {
    const at = col.findIndex((i) => i.uid === uid);
    if (at >= 0) item = col.splice(at, 1)[0];
  }
  if (!item || column < 0 || column >= layout.columns.length) return value;
  const target = layout.columns[column];
  target.splice(Math.max(0, Math.min(index, target.length)), 0, item);
  return next;
}

export function removeItem(value: PageLayout, n: ColumnCount, uid: string): PageLayout {
  const next = clone(value);
  const layout = next.layouts[n - 1];
  layout.columns = layout.columns.map((col) => col.filter((i) => i.uid !== uid));
  return next;
}

/** Column ``column`` ``delta`` twelfths wider (+) / narrower (-), taken from /
 * given to its right neighbour (the last column: its left one); each column
 * keeps at least one twelfth. */
export function resizeColumn(value: PageLayout, n: ColumnCount, column: number, delta: number): PageLayout {
  if (n === 1) return value;
  const widths = [...value.layouts[n - 1].widths];
  const other = column === n - 1 ? column - 1 : column + 1;
  const width = widths[column] + delta;
  const rest = widths[other] - delta;
  if (width < 1 || rest < 1) return value;
  widths[column] = width;
  widths[other] = rest;
  const next = clone(value);
  next.layouts[n - 1].widths = widths;
  return next;
}

/** Switch a layout on / off; the last one on stays on. */
export function setEnabled(value: PageLayout, n: ColumnCount, enabled: boolean): PageLayout {
  if (!enabled && value.layouts.filter((l) => l.enabled).length <= 1 && value.layouts[n - 1].enabled) return value;
  const next = clone(value);
  next.layouts[n - 1].enabled = enabled;
  return next;
}

// -- showing ----------------------------------------------------------------- //

/**
 * The layout a page of ``width`` px uses: the most columns of the enabled
 * layouts in which every column is at least :data:`MIN_COLUMN_PX` wide;
 * when none fits, the fewest-column enabled one — its columns then wrap
 * one below the other.
 */
export function chooseLayout(value: PageLayout, width: number, gap = 24): ColumnCount {
  const enabled = COLUMN_COUNTS.filter((n) => value.layouts[n - 1].enabled);
  for (const n of [...enabled].reverse()) {
    const usable = width - gap * (n - 1);
    if (value.layouts[n - 1].widths.every((w) => (usable * w) / GRID >= MIN_COLUMN_PX)) return n;
  }
  return enabled[0] ?? 1;
}

/** The page width (px) from which the ``n``-column layout fits. */
export function minPageWidth(value: PageLayout, n: ColumnCount, gap = 24): number {
  const widths = value.layouts[n - 1].widths;
  return Math.ceil(Math.max(...widths.map((w) => (MIN_COLUMN_PX * GRID) / w)) + gap * (n - 1));
}
