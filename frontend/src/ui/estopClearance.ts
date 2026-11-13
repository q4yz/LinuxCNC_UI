// The E-stop box (EStopHeader) is fixed to the top-right corner, over the
// page. A card header under it — the top-right card, with the page
// scrolled to the top — would have its right-hand buttons covered:
// BaseCard pads the header by what this returns.

/** Space kept between the header's buttons and the E-stop box (px). */
export const ESTOP_GAP_PX = 8;

export interface Box {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

/**
 * How far (px) the header's right edge must move left to clear the
 * E-stop box; 0 when it is not under it. ``header`` is the header's
 * viewport rect, ``scrollTop`` its scroll container's offset (the check is
 * made with the page scrolled to the top: the E-stop is fixed, the page
 * scrolls under it), ``estop`` the E-stop box's viewport rect.
 */
export function estopOverlap(header: Box, estop: Box, scrollTop: number): number {
  const top = header.top + scrollTop;
  const bottom = header.bottom + scrollTop;
  const under = top < estop.bottom && bottom > estop.top && header.right > estop.left && header.left < estop.right;
  return under ? Math.ceil(header.right - estop.left + ESTOP_GAP_PX) : 0;
}

/** The E-stop box, if mounted. */
export function estopBox(): Box | null {
  const el = typeof document === "undefined" ? null : document.querySelector("[data-estop-overlay]");
  return el ? el.getBoundingClientRect() : null;
}

/** The scroll offset of ``el``'s nearest scrolling ancestor. */
export function scrollTopOf(el: HTMLElement): number {
  let node: HTMLElement | null = el.parentElement;
  while (node) {
    const style = getComputedStyle(node);
    if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight) return node.scrollTop;
    node = node.parentElement;
  }
  return window.scrollY;
}
