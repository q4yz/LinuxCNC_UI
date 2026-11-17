// Panel id (``pagePanels.PANELS``) -> its component: the pages' layouts
// (``PageLayout.vue``) and the floating windows a macro button opens
// (``FloatingPanelHost.vue``) render the same panels.
import type { Component } from "vue";

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

export const PANEL_COMPONENTS: Record<string, Component> = {
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
