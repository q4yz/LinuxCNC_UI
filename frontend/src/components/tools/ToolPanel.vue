<script setup lang="ts">
// Tools panel. One tab per tool from the base-thread snapshot
// (``toolsStore.toolList``), each with its live reading (°C, RPM);
// the body is the selected tool's card, dispatched on the entity class.

import { computed } from "vue";
import { storeToRefs } from "pinia";

import AnalogSpindleCard from "./AnalogSpindleCard.vue";
import ExtruderCard from "./ExtruderCard.vue";
import HeatedBedCard from "./HeatedBedCard.vue";
import SpindleCard from "./SpindleCard.vue";
import { heaterStatus } from "./heaterView";
import { Extruder } from "../../entities/tools/Extruder";
import { HeaterState } from "../../entities/tools/Heater";
import { SpindleAnalog } from "../../entities/tools/SpindleAnalog";
import { SpindleDigital } from "../../entities/tools/SpindleDigital";
import type { ToolItem } from "../../entities/tools/ToolList";
import { useToolStore } from "../../stores/toolsStore";
import BaseCard from "../../ui/BaseCard.vue";

const toolStore = useToolStore();
const { toolList, selectedToolId, selectedTool } = storeToRefs(toolStore);

const tools = computed<ToolItem[]>(() => toolList.value?.all() ?? []);

function heaterOf(tool: ToolItem): HeaterState | null {
  if (tool instanceof HeaterState) return tool;
  if (tool instanceof Extruder) return tool.heater;
  return null;
}

/** The short live reading on a tab. */
function reading(tool: ToolItem): string {
  const heater = heaterOf(tool);
  if (heater) return `${Math.round(heater.actualCelsius)}°`;
  if (tool instanceof SpindleDigital) return tool.actualRpm == null ? "—" : `${Math.round(tool.actualRpm)} rpm`;
  if (tool instanceof SpindleAnalog) return tool.isEnabled ? "on" : "off";
  return "";
}

function dotClass(tool: ToolItem): string {
  const heater = heaterOf(tool);
  if (heater) {
    const s = heaterStatus(heater);
    return s === "at-temp" ? "bg-green-400" : s === "heating" ? "bg-orange-400" : s === "cooling" ? "bg-sky-400" : "bg-gray-500";
  }
  if (tool instanceof SpindleDigital) return tool.isRunning ? "bg-green-400" : "bg-gray-500";
  if (tool instanceof SpindleAnalog) return tool.isEnabled ? "bg-green-400" : "bg-gray-500";
  return "bg-gray-500";
}

const extruder = computed(() => (selectedTool.value instanceof Extruder ? selectedTool.value : null));
const heater = computed(() => (selectedTool.value instanceof HeaterState ? selectedTool.value : null));
const spindle = computed(() => (selectedTool.value instanceof SpindleDigital ? selectedTool.value : null));
const analogSpindle = computed(() => (selectedTool.value instanceof SpindleAnalog ? selectedTool.value : null));
</script>

<template>
  <BaseCard title="Tools" class="min-w-[320px]">
    <div v-if="tools.length > 0" class="space-y-4 p-3">
      <div class="flex flex-wrap gap-2" role="tablist" data-testid="tool-tabs">
        <button
          v-for="tool in tools"
          :key="tool.id"
          type="button"
          role="tab"
          :aria-selected="tool.id === selectedToolId"
          class="flex items-center gap-2 px-3 py-1.5 rounded border text-xs transition-colors"
          :class="tool.id === selectedToolId
            ? 'bg-blue-600/20 border-blue-500 text-white'
            : 'bg-gray-800 border-gray-700 text-gray-300 hover:bg-gray-700'"
          @click="toolStore.setSelectedToolId(tool.id)"
        >
          <span class="w-2 h-2 rounded-full" :class="dotClass(tool)" />
          <span class="font-semibold uppercase tracking-wider">{{ tool.id }}</span>
          <span class="font-mono text-gray-400">{{ reading(tool) }}</span>
        </button>
      </div>

      <ExtruderCard v-if="extruder" :tool="extruder" />
      <HeatedBedCard v-else-if="heater" :tool="heater" />
      <SpindleCard v-else-if="spindle" :tool="spindle" />
      <AnalogSpindleCard v-else-if="analogSpindle" :tool="analogSpindle" />
      <div v-else class="text-sm text-gray-400 italic">Select a tool.</div>
    </div>

    <div v-else class="p-3 text-sm text-gray-400 italic">No tools configured yet.</div>
  </BaseCard>
</template>
