<script setup lang="ts">
// Editor for a PageLayoutSetting (Settings -> Page layout).
//
//  * Tabs: the page's 1 / 2 / 3 column layouts, each switched on or off
//    (the page picks the widest enabled one that fits its width; the last
//    one on stays on).
//  * Each column's width in twelfths (− / +, taken from its neighbour).
//  * Panels are dragged — within a column, to another column, or onto the
//    bin that appears while dragging (removes it). Mouse / pen drag the
//    whole card, a finger its grip (so the page still scrolls by touch).
//  * The round + button adds a panel at the end of the first column; a
//    panel may be added more than once.
// Every change saves.
import { computed, onBeforeUnmount, ref } from "vue";
import { Icon } from "../../ui";
import {
  COLUMN_COUNTS, GRID, PANELS, addPanel, minPageWidth, moveItem, panelDef, removeItem, resizeColumn, setEnabled,
  type ColumnCount, type PageLayout, type PanelItem,
} from "../../layout/pagePanels";
import type { PageLayoutSetting } from "../types/PageLayoutSetting";

const props = defineProps<{ setting: PageLayoutSetting }>();

const value = computed<PageLayout>(() => props.setting.value ?? props.setting.defaultValue);
const save = (next: PageLayout) => {
  if (next !== value.value) void props.setting.save(next);
};

const active = ref<ColumnCount>(2);
const layout = computed(() => value.value.layouts[active.value - 1]);
const layouts = (n: ColumnCount) => value.value.layouts[n - 1];
const label = (n: ColumnCount) => (n === 1 ? "1 column" : `${n} columns`);

function toggle(n: ColumnCount) {
  save(setEnabled(value.value, n, !value.value.layouts[n - 1].enabled));
}
const lastOn = (n: ColumnCount) =>
  value.value.layouts[n - 1].enabled && value.value.layouts.filter((l) => l.enabled).length === 1;

// -- adding ------------------------------------------------------------------ //
const pickerOpen = ref(false);
function add(panel: string) {
  save(addPanel(value.value, active.value, panel));
  pickerOpen.value = false;
}

// -- dragging (pointer events: mouse, pen and touch alike) ------------------- //
interface Drag {
  item: PanelItem;
  pointerId: number;
  startX: number;
  startY: number;
  started: boolean;
  x: number;
  y: number;
  width: number;
}
const drag = ref<Drag | null>(null);
/** Where a drop would land: a column and the index in it, or the bin. */
const target = ref<{ column: number; index: number } | "bin" | null>(null);
const DRAG_THRESHOLD = 6;

function onPointerDown(item: PanelItem, event: PointerEvent) {
  if (event.button !== 0) return;
  const handle = (event.target as HTMLElement).closest("[data-drag-handle]");
  if (event.pointerType === "touch" && !handle) return; // a finger elsewhere scrolls
  const card = event.currentTarget as HTMLElement;
  drag.value = {
    item, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, started: false,
    x: event.clientX, y: event.clientY, width: card.getBoundingClientRect().width,
  };
  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp);
  window.addEventListener("pointercancel", cancel);
}

function onPointerMove(event: PointerEvent) {
  const d = drag.value;
  if (!d || event.pointerId !== d.pointerId) return;
  if (!d.started && Math.hypot(event.clientX - d.startX, event.clientY - d.startY) < DRAG_THRESHOLD) return;
  d.started = true;
  d.x = event.clientX;
  d.y = event.clientY;
  event.preventDefault();
  target.value = hitTest(event.clientX, event.clientY, d.item.uid);
}

function hitTest(x: number, y: number, uid: string): { column: number; index: number } | "bin" | null {
  const element = document.elementFromPoint(x, y) as HTMLElement | null;
  if (!element) return null;
  if (element.closest("[data-layout-bin]")) return "bin";
  const column = element.closest<HTMLElement>("[data-layout-column]");
  if (!column) return null;
  // the index among the column's other cards: before the first whose middle is below the pointer
  const cards = Array.from(column.querySelectorAll<HTMLElement>("[data-layout-item]"))
    .filter((card) => card.dataset.uid !== uid);
  let index = cards.length;
  for (let k = 0; k < cards.length; k++) {
    const box = cards[k].getBoundingClientRect();
    if (y < box.top + box.height / 2) {
      index = k;
      break;
    }
  }
  return { column: Number(column.dataset.column), index };
}

function onPointerUp(event: PointerEvent) {
  const d = drag.value;
  if (!d || event.pointerId !== d.pointerId) return;
  const where = d.started ? hitTest(event.clientX, event.clientY, d.item.uid) : null;
  cancel();
  if (where === "bin") save(removeItem(value.value, active.value, d.item.uid));
  else if (where) save(moveItem(value.value, active.value, d.item.uid, where.column, where.index));
}

function cancel() {
  drag.value = null;
  target.value = null;
  window.removeEventListener("pointermove", onPointerMove);
  window.removeEventListener("pointerup", onPointerUp);
  window.removeEventListener("pointercancel", cancel);
}
onBeforeUnmount(cancel);

const dragging = computed(() => drag.value?.started === true);
/** The column's cards as shown while dragging: the dragged one taken out. */
function shown(column: PanelItem[]): PanelItem[] {
  return dragging.value ? column.filter((i) => i.uid !== drag.value?.item.uid) : column;
}
const dropHere = (column: number, index: number) =>
  dragging.value && target.value !== null && target.value !== "bin" &&
  target.value.column === column && target.value.index === index;
</script>

<template>
  <div class="relative w-full space-y-3 pb-16" :data-testid="`setting-${setting.key}`">
    <!-- the three layouts: pick one to edit, switch each on / off -->
    <div class="flex flex-wrap items-center gap-2" role="tablist">
      <div
          v-for="n in COLUMN_COUNTS"
          :key="n"
          class="flex items-center overflow-hidden rounded border text-sm"
          :class="active === n ? 'border-blue-500 bg-blue-600/20' : 'border-gray-600 bg-gray-800'"
      >
        <button
            type="button"
            role="tab"
            class="flex items-center gap-2 px-3 py-1.5"
            :class="[active === n ? 'text-white' : 'text-gray-300 hover:text-white', layouts(n).enabled ? '' : 'opacity-50']"
            :aria-selected="active === n"
            :data-testid="`layout-tab-${setting.page}-${n}`"
            @click="active = n"
        >
          <span class="flex h-4 gap-0.5" aria-hidden="true">
            <span v-for="c in n" :key="c" class="w-1.5 rounded-sm bg-current" />
          </span>
          {{ label(n) }}
        </button>
        <label
            class="flex cursor-pointer items-center border-l border-gray-600 px-2 py-1.5"
            :title="lastOn(n) ? 'The last layout on stays on' : layouts(n).enabled ? 'On: the page may use it' : 'Off: never used'"
        >
          <input
              type="checkbox"
              class="h-4 w-4 accent-blue-500"
              :checked="layouts(n).enabled"
              :disabled="lastOn(n)"
              :aria-label="`Use the ${label(n)} layout`"
              :data-testid="`layout-enable-${setting.page}-${n}`"
              @change="toggle(n)"
          />
        </label>
      </div>
    </div>
    <p class="text-xs text-gray-500">
      <template v-if="layout.enabled">
        {{ active === 1 ? "Used when no wider layout fits." : `Used from about ${minPageWidth(value, active)} px page width.` }}
      </template>
      <template v-else>Off — the page does not use it{{ active > 1 ? " (a narrower layout, or its columns wrap)" : "" }}.</template>
      Drag panels to order and place them; drop one on the bin to remove it.
    </p>

    <!-- the columns, 12 segments wide -->
    <div class="grid gap-3" :style="{ gridTemplateColumns: `repeat(${GRID}, minmax(0, 1fr))` }">
      <section
          v-for="(column, c) in layout.columns"
          :key="`${active}-${c}`"
          class="flex min-h-[8rem] flex-col rounded border bg-gray-900/40 p-2"
          :class="dragging && target !== 'bin' && target?.column === c ? 'border-blue-500' : 'border-gray-700'"
          :style="{ gridColumn: `span ${layout.widths[c]} / span ${layout.widths[c]}` }"
          data-layout-column
          :data-column="c"
          :data-testid="`layout-column-${setting.page}-${active}-${c}`"
      >
        <header class="mb-2 flex items-center justify-between gap-1 text-xs text-gray-400">
          <span class="font-semibold uppercase tracking-wider">Column {{ c + 1 }}</span>
          <span v-if="active > 1" class="flex items-center gap-1">
            <button type="button" class="rounded bg-gray-700 px-1.5 leading-5 hover:bg-gray-600 disabled:opacity-40"
                    :disabled="layout.widths[c] <= 1" :aria-label="`Column ${c + 1} narrower`"
                    @click="save(resizeColumn(value, active, c, -1))">−</button>
            <span class="w-9 text-center font-mono" :data-testid="`layout-width-${setting.page}-${active}-${c}`">{{ layout.widths[c] }}/{{ GRID }}</span>
            <button type="button" class="rounded bg-gray-700 px-1.5 leading-5 hover:bg-gray-600 disabled:opacity-40"
                    :disabled="layout.widths[c === active - 1 ? c - 1 : c + 1] <= 1" :aria-label="`Column ${c + 1} wider`"
                    @click="save(resizeColumn(value, active, c, 1))">+</button>
          </span>
        </header>
        <ul class="flex flex-1 flex-col gap-1.5">
          <template v-for="(item, k) in shown(column)" :key="item.uid">
            <li v-if="dropHere(c, k)" class="h-1 rounded bg-blue-500" aria-hidden="true" />
            <li
                class="flex cursor-grab select-none items-center gap-2 rounded border border-gray-600 bg-gray-800 px-2 py-2 text-sm text-gray-200 hover:border-gray-500"
                data-layout-item
                :data-uid="item.uid"
                :data-testid="`layout-item-${setting.page}-${item.panel}`"
                @pointerdown="onPointerDown(item, $event)"
            >
              <span data-drag-handle class="touch-none px-1 text-gray-500" aria-hidden="true">⠿</span>
              <span class="min-w-0 flex-1 truncate">{{ panelDef(item.panel)?.label ?? item.panel }}</span>
            </li>
          </template>
          <li v-if="dropHere(c, shown(column).length)" class="h-1 rounded bg-blue-500" aria-hidden="true" />
          <li v-if="!shown(column).length" class="flex flex-1 items-center justify-center rounded border border-dashed border-gray-700 py-4 text-xs text-gray-500">
            {{ dragging ? "Drop here" : "Empty" }}
          </li>
        </ul>
      </section>
    </div>

    <!-- add a panel: the blue round + in the corner -->
    <div class="absolute bottom-0 right-0 flex flex-col items-end gap-2">
      <div
          v-if="pickerOpen"
          class="max-h-80 w-56 overflow-y-auto rounded-lg border border-gray-600 bg-gray-800 p-1"
          role="menu"
          :data-testid="`layout-picker-${setting.page}`"
      >
        <p class="px-2 py-1 text-[11px] uppercase tracking-wider text-gray-500">Add to column 1</p>
        <button
            v-for="panel in PANELS"
            :key="panel.id"
            type="button"
            role="menuitem"
            class="block w-full rounded px-2 py-1.5 text-left text-sm text-gray-200 hover:bg-gray-700"
            :data-testid="`layout-add-${setting.page}-${panel.id}`"
            @click="add(panel.id)"
        >{{ panel.label }}</button>
      </div>
      <button
          type="button"
          class="flex h-12 w-12 items-center justify-center rounded-full bg-blue-600 text-3xl leading-none text-white hover:bg-blue-500"
          :title="pickerOpen ? 'Close' : 'Add a panel'"
          :aria-label="pickerOpen ? 'Close' : 'Add a panel'"
          :aria-expanded="pickerOpen"
          :data-testid="`layout-add-button-${setting.page}`"
          @click="pickerOpen = !pickerOpen"
      >{{ pickerOpen ? "×" : "+" }}</button>
    </div>

    <!-- while dragging: the card under the pointer and the bin -->
    <Teleport to="body">
      <div
          v-if="dragging && drag"
          class="pointer-events-none fixed z-50 rounded border border-blue-400 bg-gray-800/95 px-3 py-2 text-sm text-gray-100"
          :style="{ left: `${drag.x + 8}px`, top: `${drag.y + 8}px`, width: `${Math.min(drag.width, 280)}px` }"
      >{{ panelDef(drag.item.panel)?.label ?? drag.item.panel }}</div>
      <div
          v-if="dragging"
          class="fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-full border-2 px-6 py-3 text-sm font-semibold transition-transform"
          :class="target === 'bin' ? 'scale-110 border-red-400 bg-red-600 text-white' : 'border-red-500/60 bg-gray-900/95 text-red-300'"
          data-layout-bin
          :data-testid="`layout-bin-${setting.page}`"
      >
        <Icon name="trash" class="h-6 w-6" /> Drop here to remove
      </div>
    </Teleport>
  </div>
</template>
