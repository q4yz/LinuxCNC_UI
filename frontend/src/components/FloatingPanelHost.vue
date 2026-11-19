<script setup lang="ts">
// The floating panel windows (``useFloatingPanels``). A window has no frame
// or header of its own: it hands its × and its drag to the panel's own card
// header (``windowChrome``: BaseCard takes it). Only while nothing inside
// takes it (a panel without a card header, the offline placeholder) does
// the window show a slim header itself. A click anywhere brings a window to
// the front.
import { onBeforeUnmount, provide, reactive } from "vue";
import MachineGate from "./machine/MachineGate.vue";
import ConsolePanel from "./ConsolePanel.vue";
import WindowCloseButton from "../ui/WindowCloseButton.vue";
import { PANEL_COMPONENTS } from "../layout/panelComponents";
import { panelDef } from "../layout/pagePanels";
import { useFloatingPanels, type FloatingPanel } from "../composables/useFloatingPanels";
import { NO_DRAG, WINDOW_CHROME, type WindowChrome } from "../composables/windowChrome";

const { windows, close, focus, moveTo, WIDTH } = useFloatingPanels();

// -- dragging ------------------------------------------------------------- //
let dragging: { id: string; pointerId: number; dx: number; dy: number } | null = null;

function startDrag(win: FloatingPanel, event: PointerEvent) {
  if (event.button !== 0 || (event.target as HTMLElement).closest(NO_DRAG)) return;
  focus(win.id);
  dragging = { id: win.id, pointerId: event.pointerId, dx: event.clientX - win.x, dy: event.clientY - win.y };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", stop);
  window.addEventListener("pointercancel", stop);
  event.preventDefault();
}

function onMove(event: PointerEvent) {
  if (!dragging || event.pointerId !== dragging.pointerId) return;
  moveTo(dragging.id, event.clientX - dragging.dx, event.clientY - dragging.dy);
}

function stop() {
  dragging = null;
  window.removeEventListener("pointermove", onMove);
  window.removeEventListener("pointerup", stop);
  window.removeEventListener("pointercancel", stop);
}
onBeforeUnmount(stop);

// -- the hook each window offers its panel ---------------------------------- //
const claims = reactive<Record<string, number>>({});
const chromes = new Map<string, WindowChrome>();

function chromeFor(win: FloatingPanel): WindowChrome {
  let chrome = chromes.get(win.id);
  if (!chrome) {
    chrome = {
      title: win.title,
      close: () => {
        chromes.delete(win.id);
        delete claims[win.id];
        close(win.id);
      },
      startDrag: (event: PointerEvent) => startDrag(win, event),
      claim: () => { claims[win.id] = (claims[win.id] ?? 0) + 1; },
      release: () => { claims[win.id] = Math.max(0, (claims[win.id] ?? 1) - 1); },
    };
    chromes.set(win.id, chrome);
  }
  return chrome;
}

/** Provides one window's hook to the panel inside it. */
const ChromeScope = {
  props: { chrome: { type: Object, required: true } },
  setup(props: { chrome: WindowChrome }, { slots }: { slots: { default?: () => unknown } }) {
    provide(WINDOW_CHROME, props.chrome);
    return () => slots.default?.();
  },
};
</script>

<template>
  <div
      v-for="win in windows"
      :key="win.id"
      class="fixed flex max-h-[85vh] flex-col overflow-y-auto rounded-lg"
      :style="{ left: `${win.x}px`, top: `${win.y}px`, zIndex: 60 + win.z, width: `min(${WIDTH}px, calc(100vw - 16px))` }"
      role="dialog"
      :aria-label="win.title"
      :data-testid="`floating-panel-${win.panel}`"
      @pointerdown="focus(win.id)"
  >
    <!-- nothing inside took the header hook: the window's own slim header -->
    <header
        v-if="!claims[win.id]"
        class="flex cursor-move touch-none select-none items-center justify-between gap-2 rounded-t-lg border-b border-gray-700 bg-gray-800 px-3 py-1.5"
        :data-testid="`floating-panel-title-${win.panel}`"
        @pointerdown="startDrag(win, $event)"
    >
      <span class="truncate text-sm font-semibold text-gray-300">{{ win.title }}</span>
      <WindowCloseButton :chrome="chromeFor(win)" />
    </header>
    <ChromeScope :chrome="chromeFor(win)">
      <div v-if="win.panel === 'console'" class="h-[300px]">
        <ConsolePanel />
      </div>
      <MachineGate v-else-if="PANEL_COMPONENTS[win.panel]" :label="panelDef(win.panel)?.gate ?? win.panel">
        <component :is="PANEL_COMPONENTS[win.panel]" />
      </MachineGate>
      <p v-else class="bg-gray-900 p-4 text-sm text-gray-400">This component no longer exists.</p>
    </ChromeScope>
  </div>
</template>
