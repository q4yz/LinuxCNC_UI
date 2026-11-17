// Floating windows with a panel inside (a macro button of kind "component"
// opens one): any number, each dragged by its title bar, closed with its ×,
// brought to the front when clicked. ``FloatingPanelHost`` (App.vue)
// renders them. State lives in this browser tab only.
import { reactive } from "vue";

export interface FloatingPanel {
  /** Window id; one window per panel id (opening it again brings it up). */
  id: string;
  panel: string;
  title: string;
  x: number;
  y: number;
  z: number;
}

const state = reactive<{ windows: FloatingPanel[]; top: number }>({ windows: [], top: 100 });
const WIDTH = 520;

export function useFloatingPanels() {
  function open(panel: string, title: string) {
    const existing = state.windows.find((w) => w.panel === panel);
    if (existing) {
      focus(existing.id);
      return;
    }
    const k = state.windows.length;
    const vw = typeof window !== "undefined" ? window.innerWidth : 1280;
    state.windows.push({
      id: `float-${panel}`,
      panel,
      title,
      // centred near the top, each new one a little lower right
      x: Math.max(8, Math.round((vw - Math.min(WIDTH, vw - 16)) / 2) + k * 32),
      y: 80 + k * 32,
      z: ++state.top,
    });
  }

  function close(id: string) {
    const index = state.windows.findIndex((w) => w.id === id);
    if (index >= 0) state.windows.splice(index, 1);
  }

  function focus(id: string) {
    const win = state.windows.find((w) => w.id === id);
    if (win && win.z !== state.top) win.z = ++state.top;
  }

  function moveTo(id: string, x: number, y: number) {
    const win = state.windows.find((w) => w.id === id);
    if (!win) return;
    const vw = typeof window !== "undefined" ? window.innerWidth : 1280;
    const vh = typeof window !== "undefined" ? window.innerHeight : 800;
    // the title bar stays reachable: at least 80 px on screen, never above the top
    win.x = Math.min(Math.max(x, 80 - WIDTH), vw - 80);
    win.y = Math.min(Math.max(y, 0), vh - 40);
  }

  return { windows: state.windows, open, close, focus, moveTo, WIDTH };
}
