// Shared, per-browser setting controlling whether the 3D viewer's
// machine-limits grid is drawn. Purely a display preference (like
// useRenderQuality.ts) — no backend module owns this, so it's kept
// in localStorage rather than round-tripping through a settings API.
// Defaults to shown, so nothing changes visually until someone opts
// out (e.g. to shave a little more render cost on weak hardware, or
// simply because they don't want the clutter). State is module-scope
// so every viewer instance and the settings control share one value.

import { ref } from "vue";

const STORAGE_KEY = "linuxcnc.viewerShowGrid";

function readStored(): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    // Absent key (first run) defaults to shown; anything else must
    // be the literal "false" to turn it off.
    return raw === null ? true : raw !== "false";
  } catch {
    return true;
  }
}

const showGrid = ref<boolean>(readStored());

function setShowGrid(next: boolean): void {
  showGrid.value = next;
  try {
    localStorage.setItem(STORAGE_KEY, String(next));
  } catch {
    // Best-effort — a private-browsing localStorage throw must not
    // break the viewer.
  }
}

export function useViewerGridSetting() {
  return {
    showGrid,
    setShowGrid,
    toggleShowGrid: () => setShowGrid(!showGrid.value),
  };
}

export default useViewerGridSetting;
