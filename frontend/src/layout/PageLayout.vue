<script setup lang="ts">
// A page's panels (Dashboard / Running) in the layout its setting holds
// (Settings -> Page layout): one, two or three columns — whichever enabled
// layout the page's width fits — top to bottom; a panel placed twice shows
// twice, one not placed is not mounted. Machine panels mount inside
// ``MachineGate`` (only while the machine backend is reachable); the
// console never is gated.
import { computed, onBeforeUnmount, onMounted, ref, type Component } from "vue";

import ConsolePanel from "../components/ConsolePanel.vue";
import ActivePrintWidget from "../components/ActivePrintWidget.vue";
import CameraViewer from "../components/camera/CameraViewer.vue";
import TemperaturePanel from "../components/temperature/TemperaturePanel.vue";
import IoPanel from "../components/io/IoPanel.vue";
import LedPanel from "../components/io/LedPanel.vue";
import DroPanel from "../components/machine/DroPanel.vue";
import JogControls from "../components/machine/JogControls.vue";
import AxisSpeedControl from "../components/machine/AxisSpeedControl.vue";
import ToolPanel from "../components/tools/ToolPanel.vue";
import MacroPanel from "../components/macros/MacroPanel.vue";
import McodePanel from "../components/macros/McodePanel.vue";
import PowerOn from "../components/machine/PowerOn.vue";
import ProbingPanel from "../components/probing/ProbingPanel.vue";
import MachineGate from "../components/machine/MachineGate.vue";
import type { PageLayoutSetting } from "../settings/types/PageLayoutSetting";
import { GRID, MIN_COLUMN_PX, chooseLayout, panelDef, type PageLayout } from "./pagePanels";

const props = defineProps<{ setting: PageLayoutSetting }>();

const COMPONENTS: Record<string, Component> = {
  machine: PowerOn,
  dro: DroPanel,
  jog: JogControls,
  probe: ProbingPanel,
  tools: ToolPanel,
  temperature: TemperaturePanel,
  io: IoPanel,
  leds: LedPanel,
  job: ActivePrintWidget,
  axis_speed: AxisSpeedControl,
  console: ConsolePanel,
  camera: CameraViewer,
  macros: MacroPanel,
  mcodes: McodePanel,
};

const value = computed<PageLayout>(() => props.setting.value ?? props.setting.defaultValue);

// The page's own width picks the layout: the most columns (of the enabled
// ones) that still give every column MIN_COLUMN_PX; when none fits, the
// fewest-column one wraps its columns one below the other.
const root = ref<HTMLElement | null>(null);
const width = ref(typeof window !== "undefined" ? window.innerWidth : 1920);
let observer: ResizeObserver | null = null;
onMounted(() => {
  if (root.value) width.value = root.value.clientWidth || width.value;
  if (typeof ResizeObserver !== "undefined" && root.value) {
    observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) width.value = w; // 0 while hidden (kept alive): keep the last
    });
    observer.observe(root.value);
  }
});
onBeforeUnmount(() => observer?.disconnect());

const count = computed(() => chooseLayout(value.value, width.value));
const columns = computed(() => {
  const layout = value.value.layouts[count.value - 1];
  return layout.columns.map((items, k) => ({
    key: k,
    items: items.filter((item) => COMPONENTS[item.panel]),
    grow: layout.widths[k] ?? GRID / layout.columns.length,
  }));
});
const minWidth = `min(100%, ${MIN_COLUMN_PX}px)`;
</script>

<template>
  <div
      ref="root"
      class="flex flex-wrap gap-6 pb-8"
      :data-testid="`page-layout-${setting.page}`"
      :data-columns="count"
  >
    <div
        v-for="column in columns"
        :key="column.key"
        class="flex flex-col space-y-6"
        :style="{ flex: `${column.grow} 1 0%`, minWidth }"
    >
      <template v-for="item in column.items" :key="item.uid">
        <!-- The console: fixed height, never gated (it explains "offline"). -->
        <div v-if="item.panel === 'console'" class="h-[300px]">
          <ConsolePanel />
        </div>
        <MachineGate v-else :label="panelDef(item.panel)?.gate ?? item.panel">
          <component :is="COMPONENTS[item.panel]" />
        </MachineGate>
      </template>
    </div>
  </div>
</template>
