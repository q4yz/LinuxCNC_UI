<script setup lang="ts">
// The floating panel windows (``useFloatingPanels``): a title bar to drag
// (pointer events: mouse, pen and touch), a × to close, a click anywhere
// brings the window to the front. The panel inside is the same component
// the pages show, machine panels inside ``MachineGate``.
import { onBeforeUnmount } from "vue";
import Icon from "../ui/Icon.vue";
import MachineGate from "./machine/MachineGate.vue";
import ConsolePanel from "./ConsolePanel.vue";
import { PANEL_COMPONENTS } from "../layout/panelComponents";
import { panelDef } from "../layout/pagePanels";
import { useFloatingPanels, type FloatingPanel } from "../composables/useFloatingPanels";

const { windows, close, focus, moveTo, WIDTH } = useFloatingPanels();

let dragging: { id: string; pointerId: number; dx: number; dy: number } | null = null;

function onTitleDown(win: FloatingPanel, event: PointerEvent) {
  if (event.button !== 0 || (event.target as HTMLElement).closest("button")) return;
  focus(win.id);
  dragging = { id: win.id, pointerId: event.pointerId, dx: event.clientX - win.x, dy: event.clientY - win.y };
  (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
  event.preventDefault();
}

function onTitleMove(event: PointerEvent) {
  if (!dragging || event.pointerId !== dragging.pointerId) return;
  moveTo(dragging.id, event.clientX - dragging.dx, event.clientY - dragging.dy);
}

function onTitleUp(event: PointerEvent) {
  if (dragging && event.pointerId === dragging.pointerId) dragging = null;
}

onBeforeUnmount(() => {
  dragging = null;
});
</script>

<template>
  <div
      v-for="win in windows"
      :key="win.id"
      class="fixed flex max-h-[85vh] flex-col overflow-hidden rounded-lg border border-blue-500/60 bg-gray-900"
      :style="{ left: `${win.x}px`, top: `${win.y}px`, zIndex: 60 + win.z, width: `min(${WIDTH}px, calc(100vw - 16px))` }"
      role="dialog"
      :aria-label="win.title"
      :data-testid="`floating-panel-${win.panel}`"
      @pointerdown="focus(win.id)"
  >
    <header
        class="flex cursor-move touch-none select-none items-center justify-between gap-2 border-b border-gray-700 bg-gray-800 px-3 py-2"
        :data-testid="`floating-panel-title-${win.panel}`"
        @pointerdown="onTitleDown(win, $event)"
        @pointermove="onTitleMove"
        @pointerup="onTitleUp"
        @pointercancel="onTitleUp"
    >
      <span class="truncate text-sm font-semibold text-gray-200">{{ win.title }}</span>
      <button
          type="button"
          class="flex h-7 w-7 items-center justify-center rounded text-gray-400 hover:bg-gray-700 hover:text-white"
          :aria-label="`Close ${win.title}`"
          :data-testid="`floating-panel-close-${win.panel}`"
          @click="close(win.id)"
      ><Icon name="close" class="h-4 w-4" /></button>
    </header>
    <div class="min-h-0 flex-1 overflow-auto p-2">
      <div v-if="win.panel === 'console'" class="h-[300px]">
        <ConsolePanel />
      </div>
      <MachineGate v-else-if="PANEL_COMPONENTS[win.panel]" :label="panelDef(win.panel)?.gate ?? win.panel">
        <component :is="PANEL_COMPONENTS[win.panel]" />
      </MachineGate>
      <p v-else class="p-4 text-sm text-gray-400">This component no longer exists.</p>
    </div>
  </div>
</template>
