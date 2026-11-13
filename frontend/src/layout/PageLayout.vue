<script setup lang="ts">
// A page's panels (Dashboard / Running) in the layout its setting holds
// (Settings -> Page layout): two columns, top to bottom, hidden ones not
// mounted at all. Machine panels mount inside ``MachineGate`` (only while
// the machine backend is reachable); the console never is gated.
import { computed, type Component } from "vue";

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
import MachineGate from "../components/machine/MachineGate.vue";
import type { PageLayoutSetting } from "../settings/types/PageLayoutSetting";
import { COLUMN_RATIO, panelDef, type PageLayout } from "./pagePanels";

const props = defineProps<{ setting: PageLayoutSetting }>();

const COMPONENTS: Record<string, Component> = {
  machine: PowerOn,
  dro: DroPanel,
  jog: JogControls,
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

const layout = computed<PageLayout>(() => props.setting.value ?? props.setting.defaultValue);
const columns = computed(() => {
  const [left, right] = COLUMN_RATIO[props.setting.page];
  return [
    { key: "left", ids: layout.value.left.filter((id) => COMPONENTS[id]), grow: left, minWidth: "min(100%,570px)" },
    { key: "right", ids: layout.value.right.filter((id) => COMPONENTS[id]), grow: right, minWidth: "min(100%,600px)" },
  ].filter((column) => column.ids.length > 0);
});
</script>

<template>
  <div class="flex flex-wrap gap-6 pb-8" :data-testid="`page-layout-${setting.page}`">
    <div
        v-for="column in columns"
        :key="column.key"
        class="flex flex-col space-y-6"
        :style="{ flex: `${column.grow} 1 0%`, minWidth: column.minWidth }"
    >
      <template v-for="id in column.ids" :key="id">
        <!-- The console: fixed height, never gated (it explains "offline"). -->
        <div v-if="id === 'console'" class="h-[300px]">
          <ConsolePanel />
        </div>
        <MachineGate v-else :label="panelDef(id)?.gate ?? id">
          <component :is="COMPONENTS[id]" />
        </MachineGate>
      </template>
    </div>
  </div>
</template>
