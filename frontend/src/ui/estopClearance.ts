// The E-stop box (EStopHeader) is fixed to the top-right corner, over the
// page. Whatever card row is under it right now — the top-right card,
// any card scrolled up beneath it, the first card of a single-column
// (narrow) layout — would have its right-hand buttons covered: BaseCard
// pads that row by what ``estopOverlap`` returns, re-measured on scroll
// (of any container), resize and size changes.

/** Space kept between a row's buttons and the E-stop box (px). */
export const ESTOP_GAP_PX = 8;
/** A title-less card's first row is padded only up to this height (px):
 * a big block (a camera image) is not squeezed. */
export const MAX_ROW_PX = 120;

export interface Box {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

/**
 * How far (px) ``row``'s right edge must move left to clear the E-stop
 * box; 0 when it is not under it. Both are viewport rects (where they are
 * on screen now: the E-stop is fixed, the page scrolls under it).
 */
export function estopOverlap(row: Box, estop: Box): number {
  const under = row.top < estop.bottom && row.bottom > estop.top && row.right > estop.left && row.left < estop.right;
  return under ? Math.ceil(row.right - estop.left + ESTOP_GAP_PX) : 0;
}

/** The E-stop box, if mounted. */
export function estopBox(): Box | null {
  const el = typeof document === "undefined" ? null : document.querySelector("[data-estop-overlay]");
  return el ? el.getBoundingClientRect() : null;
}

// One scroll (capture: every scroll container) + resize listener for all
// cards; their measurements run at most once per animation frame.
const measurers = new Set<() => void>();
let frame = 0;

function runAll(): void {
  frame = 0;
  for (const measure of measurers) measure();
}

export function scheduleEstopCheck(): void {
  if (frame || typeof requestAnimationFrame === "undefined") return;
  frame = requestAnimationFrame(runAll);
}

/** Register a card's measurement; returns the unregister function. */
export function watchEstop(measure: () => void): () => void {
  if (measurers.size === 0 && typeof window !== "undefined") {
    document.addEventListener("scroll", scheduleEstopCheck, { capture: true, passive: true });
    window.addEventListener("resize", scheduleEstopCheck);
  }
  measurers.add(measure);
  return () => {
    measurers.delete(measure);
    if (measurers.size === 0 && typeof window !== "undefined") {
      document.removeEventListener("scroll", scheduleEstopCheck, { capture: true });
      window.removeEventListener("resize", scheduleEstopCheck);
    }
  };
}

// The padding a row had before it was shifted (inline value + computed px).
const original = new WeakMap<HTMLElement, { inline: string; base: number }>();

/** Pad ``el``'s right side by ``shift`` px more than its own padding; 0 restores it. */
export function applyShift(el: HTMLElement, shift: number): void {
  let saved = original.get(el);
  if (shift <= 0) {
    if (saved) {
      el.style.paddingRight = saved.inline;
      original.delete(el);
    }
    return;
  }
  if (!saved) {
    saved = { inline: el.style.paddingRight, base: parseFloat(getComputedStyle(el).paddingRight) || 0 };
    original.set(el, saved);
  }
  const value = `${saved.base + shift}px`;
  if (el.style.paddingRight !== value) el.style.paddingRight = value;
}
