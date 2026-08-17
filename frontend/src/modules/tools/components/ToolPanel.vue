<script setup lang="ts">
// Tools panel. Header shows one chip per tool reported by the
// backend; the body renders a single tool at a time, dispatched by
// `selectedTool.type`. The tool list is read from the shared
// base-thread snapshot (`stores/baseThread`).

import { storeToRefs } from "pinia";

import AnalogSpindleCard from "./AnalogSpindleCard.vue";
import ExtruderCard from "./ExtruderCard.vue";
import HeatedBedCard from "./HeatedBedCard.vue";
import SpindleCard from "./SpindleCard.vue";
import { useToolStore } from "../toolStore";

const toolStore = useToolStore();

// We completely drop the legacy `tools` array and use the strictly
// typed `toolList` entity instead.
const { toolList, selectedToolId, selectedTool } = storeToRefs(toolStore);
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden">
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex items-center justify-between gap-4">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm whitespace-nowrap">
        Tools
      </h2>
      <!-- Use toolList.size and iterate over toolList.all() -->
      <div v-if="toolList.size > 0" class="flex flex-wrap gap-2 justify-end">
        <button
            v-for="tool in toolList.all()"
            :key="tool.id"
            type="button"
            class="px-3 py-1 rounded text-xs font-semibold uppercase tracking-wider transition-colors"
            :class="tool.id === selectedToolId
            ? 'bg-blue-600 text-white shadow'
            : 'bg-gray-700 text-gray-300 hover:bg-gray-600'"
            @click="toolStore.setSelectedToolId(tool.id)"
        >
          {{ tool.id }}
        </button>
      </div>
    </div>

    <div class="p-4 space-y-4 bg-gray-700/20">
      <div
          v-if="selectedTool"
          class="bg-gray-800 border border-gray-700 rounded-lg p-4 shadow-sm"
      >
        <h3 class="text-lg font-semibold text-gray-200 mb-4">
          {{ selectedTool.id }}
        </h3>


        <AnalogSpindleCard
            v-if="selectedTool.type === 'analog_spindle'"
            :tool="selectedTool"
        />
        <SpindleCard
            v-else-if="selectedTool.type === 'digital_spindle'"
            :tool="selectedTool"
        />
        <ExtruderCard
            v-else-if="selectedTool.type === 'extruder'"
            :tool="selectedTool"
        />
        <HeatedBedCard
            v-else-if="selectedTool.type === 'heated_bed'"
            :tool="selectedTool"
        />
        <div
            v-else
            class="text-sm text-gray-400 italic"
        >
          Unknown tool type: {{ selectedTool.type }}
        </div>
      </div>

      <div
          v-else
          class="bg-gray-800 border border-gray-700 rounded-lg p-4 text-sm text-gray-400 italic shadow-sm"
      >
        No tools configured yet.
      </div>
    </div>
  </div>
</template>

<style scoped>
/* The per-type cards own their own input-spinner styling; nothing
   to add here. Kept as an empty scoped block so future panel-level
   styles have a place to land without re-introducing global
   selectors. */
</style>