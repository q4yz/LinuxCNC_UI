// Pure oscilloscope math: trigger search, window placement, scaling.
// No DOM, no Vue — unit-tested in tests/test-hal-scope.ts.

import { lowerBound } from "./ScopeBuffer";

export type TriggerEdge = "rising" | "falling";
export type TriggerMode = "auto" | "normal" | "off";

/** Display divisions, like a bench scope. */
export const X_DIVS = 10;
export const Y_DIVS = 8;

/**
 * Time of the latest `edge` crossing of `level` (linearly interpolated)
 * at or before `notAfter`. `null` gaps break a crossing. Searches back
 * only to `notBefore`.
 */
export function findTrigger(
  times: readonly number[],
  values: readonly (number | null)[],
  edge: TriggerEdge,
  level: number,
  notAfter: number,
  notBefore = -Infinity,
): number | null {
  let i = Math.min(lowerBound(times, notAfter + 1e-12), times.length) - 1;
  const stop = Math.max(1, lowerBound(times, notBefore));
  for (; i >= stop; i--) {
    const a = values[i - 1];
    const b = values[i];
    if (a === null || b === null || a === undefined || b === undefined) continue;
    const crossed = edge === "rising" ? a < level && b >= level : a > level && b <= level;
    if (!crossed) continue;
    const t0 = times[i - 1];
    const t1 = times[i];
    const frac = b === a ? 1 : (level - a) / (b - a);
    return t0 + (t1 - t0) * frac;
  }
  return null;
}

export interface WindowState {
  /** Start / end of the displayed window, seconds on the sample clock. */
  start: number;
  end: number;
  /** Trigger time when this window is a triggered one. */
  triggerAt: number | null;
}

/**
 * Where to put the display window this frame.
 *
 * * `off`  — roll: the newest `span` seconds.
 * * edge found — the trigger sits at `position` (0…1) of the window; the
 *   latest crossing that already has the full post-trigger part is used,
 *   so the picture is complete and stable.
 * * no edge — `auto` rolls (after one window without a trigger, like a
 *   bench scope's auto mode); `normal` keeps the previous triggered
 *   window (`null` until the first trigger).
 */
export function placeWindow(
  times: readonly number[],
  source: readonly (number | null)[] | null,
  opts: { span: number; position: number; mode: TriggerMode; edge: TriggerEdge; level: number },
  previous: WindowState | null,
): WindowState | null {
  const latest = times.length ? times[times.length - 1] : null;
  if (latest === null) return previous;
  const roll: WindowState = { start: latest - opts.span, end: latest, triggerAt: null };
  if (opts.mode === "off" || !source) return roll;

  const post = (1 - opts.position) * opts.span;
  const pre = opts.position * opts.span;
  const at = findTrigger(times, source, opts.edge, opts.level, latest - post, latest - post - 2 * opts.span);
  if (at !== null) return { start: at - pre, end: at + post, triggerAt: at };

  if (opts.mode === "normal") return previous;
  // auto: keep the last triggered picture for one window, then roll.
  const lastWasTriggered = previous !== null && previous.triggerAt !== null;
  if (lastWasTriggered && latest - previous.end < opts.span) return previous;
  return roll;
}

/** 1-2-5 sequence step >= `raw` (scale per division). */
export function niceStep(raw: number): number {
  if (!Number.isFinite(raw) || raw <= 0) return 1;
  const exp = Math.floor(Math.log10(raw));
  const base = 10 ** exp;
  for (const m of [1, 2, 5, 10]) {
    if (m * base >= raw * (1 - 1e-9)) return Number((m * base).toPrecision(12));
  }
  return Number((10 * base).toPrecision(12));
}

const SEQUENCE = [1, 2, 5];

/** Next / previous value in the 1-2-5 sequence (scale knobs). */
export function stepScale(value: number, direction: 1 | -1): number {
  const current = niceStep(value);
  let exp = Math.floor(Math.log10(current) + 1e-9);
  let index = SEQUENCE.indexOf(Math.round(current / 10 ** exp));
  if (index < 0) index = 0;
  index += direction;
  if (index > 2) {
    index = 0;
    exp += 1;
  } else if (index < 0) {
    index = 2;
    exp -= 1;
  }
  // toPrecision strips float noise (2 * 10 ** -3 = 0.0020000000000000005).
  return Number((SEQUENCE[index] * 10 ** exp).toPrecision(12));
}

/** Scale + offset (in divisions) that fit `[min, max]` into ~6 of the 8 divisions. */
export function autoScale(values: readonly (number | null)[]): { scale: number; offset: number } | null {
  let min = Infinity;
  let max = -Infinity;
  for (const v of values) {
    if (v === null || v === undefined) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (min === Infinity) return null;
  const range = max - min;
  const scale = niceStep(range > 0 ? range / 6 : Math.max(Math.abs(max), 1) / 2);
  // Offset in whole hundredths of a division — readable, and plenty precise.
  const offset = Math.round((-((max + min) / 2) / scale) * 100) / 100;
  return { scale, offset: offset === 0 ? 0 : offset };
}

/** Human time per division, e.g. 0.002 → "2 ms". */
export function formatTime(seconds: number): string {
  const abs = Math.abs(seconds);
  if (abs >= 1) return `${+seconds.toFixed(3)} s`;
  if (abs >= 1e-3) return `${+(seconds * 1e3).toFixed(3)} ms`;
  return `${+(seconds * 1e6).toFixed(1)} µs`;
}

export function formatValue(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (Number.isInteger(value)) return String(value);
  const abs = Math.abs(value);
  return abs >= 1000 || abs < 0.001 ? value.toExponential(3) : value.toFixed(4).replace(/\.?0+$/, "");
}
