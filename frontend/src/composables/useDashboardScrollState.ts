// Shared "is the Dashboard actively scrolling" signal.
//
// The Dashboard hosts two live, continuously-redrawing canvases — the
// shared 3D toolpath viewer and the temperature chart — sitting in
// the same scrollable column as every other panel. Scrolling past
// them competes with those canvases for the same CPU raster thread
// on a GPU-less target; a redraw that lands mid-gesture is a
// plausible dropped frame. Freezing both while a scroll is in
// progress (and for a short settle window after it stops — covering
// momentum/inertia scrolling, which keeps firing ``scroll`` events
// throughout its own deceleration) trades a briefly-frozen canvas for
// a smooth scroll, which is the right trade since the operator is
// looking at the scroll, not the canvas, during the gesture.
//
// DashboardView owns the actual scrollable element and calls
// ``markScrolling()`` on its own ``scroll`` event; App.vue (the
// shared 3D viewer's owner) and TemperaturePanel (the chart) both
// read ``isScrolling`` to pause their own redraws. Singleton state
// (module scope, same pattern as ``useMachineOnline``) so every
// consumer shares the one signal without prop-drilling it through
// the view tree.

import { ref } from "vue";

// How long to wait after the last scroll event before treating the
// gesture as finished. Scroll events fire continuously while
// position is still changing (including during momentum/inertia
// deceleration), so this only starts counting down once movement
// actually stops.
const SETTLE_MS = 150;

const isScrolling = ref(false);
let settleTimer: ReturnType<typeof setTimeout> | null = null;

function markScrolling(): void {
  isScrolling.value = true;
  if (settleTimer !== null) clearTimeout(settleTimer);
  settleTimer = setTimeout(() => {
    settleTimer = null;
    isScrolling.value = false;
  }, SETTLE_MS);
}

export function useDashboardScrollState() {
  return { isScrolling, markScrolling };
}

export default useDashboardScrollState;
