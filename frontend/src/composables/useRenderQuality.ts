// Shared, per-browser setting controlling 3D-viewer render quality.
//
// Defaults to "high" (antialias + full devicePixelRatio) so nothing
// changes visually until someone opts out. On a GPU-less Raspberry
// Pi 4, antialiasing and a >1 device pixel ratio both multiply the
// per-pixel work of every WebGL render pass; "low" trades that
// polish for a lighter render. Persisted in localStorage (not a
// backend settings module — there's no ``viewer`` module on the
// backend, and this is a purely client-side rendering knob) so the
// choice survives reloads. State is module-scope so every viewer
// instance and the toggle control share one value.

import { ref } from "vue";

const STORAGE_KEY = "linuxcnc.viewerRenderQuality";

export type RenderQuality = "high" | "low";

function readStored(): RenderQuality {
  try {
    return localStorage.getItem(STORAGE_KEY) === "low" ? "low" : "high";
  } catch {
    return "high";
  }
}

const quality = ref<RenderQuality>(readStored());

function setQuality(next: RenderQuality): void {
  quality.value = next;
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // Best-effort — a private-browsing localStorage throw must not
    // break the viewer.
  }
}

export function useRenderQuality() {
  return {
    quality,
    setQuality,
    toggleQuality: () => setQuality(quality.value === "high" ? "low" : "high"),
    /**
     * WebGLRenderer constructor options for the current setting.
     * ``antialias`` can only be set at context creation — flipping
     * this while a viewer is already mounted takes effect on its
     * next mount, not live.
     */
    rendererOptions: (): { antialias: boolean } => ({
      antialias: quality.value === "high",
    }),
    /** Device pixel ratio cap for the current setting (this one CAN apply live). */
    pixelRatioFor: (devicePixelRatio: number): number =>
      quality.value === "high" ? devicePixelRatio : Math.min(devicePixelRatio, 1),
    /**
     * Internal render-resolution scale for the current setting, applied
     * on top of ``pixelRatioFor`` via ``renderer.setSize(w * scale, h *
     * scale, false)``. The ``false`` keeps the canvas's on-screen CSS
     * box at full container size while shrinking only the WebGL drawing
     * buffer — the browser upscales it back visually. This matters most
     * for a viewer whose canvas fills most of the screen (unlike a
     * small preview panel): a weak GPU's fill rate (pixels it can color
     * per second) scales with total on-screen pixels regardless of
     * scene complexity, so halving the buffer resolution cuts that cost
     * ~4x for a small, mostly-unnoticeable softness. This one CAN apply
     * live too.
     */
    renderScaleFor: (): number => (quality.value === "high" ? 1 : 0.5),
  };
}

export default useRenderQuality;
