<script setup lang="ts">
// A bed mesh as a heatmap: one cell per probe point, Y up (the bed seen
// from above, front-left corner bottom-left). Red = the bed is higher
// there (positive Z offset), blue = lower; the colour scales to the
// mesh's largest deviation. With ``editable`` every cell is an input.
import { computed } from "vue";
import type { BedMeshGrid } from "../../facades/bedMeshFacade";

const props = defineProps<{ grid: BedMeshGrid; editable?: boolean }>();
const emit = defineEmits<{ (e: "update:cell", row: number, col: number, value: number): void }>();

// Rows top-down = highest Y first.
const rows = computed(() => props.grid.ys.map((y, row) => ({ y, row })).reverse());

const values = computed(() => props.grid.z.flat());
const maxAbs = computed(() => Math.max(0.001, ...values.value.map((v) => Math.abs(v))));
const stats = computed(() => {
  const v = values.value;
  const min = Math.min(...v);
  const max = Math.max(...v);
  return { min, max, range: max - min };
});

function cellColor(z: number): string {
  const t = Math.min(1, Math.abs(z) / maxAbs.value);
  const rgb = z >= 0 ? "239, 68, 68" : "59, 130, 246";
  return `rgba(${rgb}, ${0.12 + 0.78 * t})`;
}

function fmt(v: number, digits = 3): string {
  return (v >= 0 ? "+" : "") + v.toFixed(digits);
}

function onInput(row: number, col: number, event: Event) {
  const value = Number((event.target as HTMLInputElement).value);
  if (Number.isFinite(value)) emit("update:cell", row, col, value);
}
</script>

<template>
  <div class="space-y-3" data-testid="bed-mesh-heatmap">
    <div class="overflow-x-auto">
      <table class="mx-auto border-separate border-spacing-1 font-mono text-xs">
        <tbody>
          <tr v-for="{ y, row } in rows" :key="row">
            <th class="pr-2 text-right font-normal text-gray-400">Y {{ y }}</th>
            <td
              v-for="(x, col) in grid.xs"
              :key="col"
              class="h-12 min-w-16 rounded text-center text-gray-100"
              :style="{ backgroundColor: cellColor(grid.z[row][col]) }"
              :title="`X ${x}  Y ${y}  Z ${fmt(grid.z[row][col], 4)} mm`"
            >
              <input
                v-if="editable"
                type="number"
                step="0.001"
                class="w-20 rounded bg-gray-900/70 px-1 py-0.5 text-center text-gray-100"
                :value="grid.z[row][col]"
                :data-testid="`bed-mesh-cell-${row}-${col}`"
                @change="onInput(row, col, $event)"
              />
              <span v-else>{{ fmt(grid.z[row][col]) }}</span>
            </td>
          </tr>
          <tr>
            <th></th>
            <th v-for="(x, col) in grid.xs" :key="col" class="pt-1 font-normal text-gray-400">X {{ x }}</th>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="flex flex-wrap items-center justify-center gap-4 text-xs text-gray-400">
      <span>min <span class="font-mono text-blue-300">{{ fmt(stats.min) }}</span></span>
      <span>max <span class="font-mono text-red-300">{{ fmt(stats.max) }}</span></span>
      <span>range <span class="font-mono text-gray-200">{{ stats.range.toFixed(3) }}</span> mm</span>
      <span class="flex items-center gap-1">
        <span class="h-3 w-6 rounded" style="background: rgba(59, 130, 246, 0.9)"></span> lower
        <span class="h-3 w-6 rounded" style="background: rgba(239, 68, 68, 0.9)"></span> higher
      </span>
    </div>
  </div>
</template>
