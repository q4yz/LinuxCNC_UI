<script setup lang="ts">
// Editor for the per-sensor colour map. One swatch row per sensor the
// dashboard currently reports. Saves on ``change`` (picker closed), not
// on every ``input`` tick, so dragging through the palette is one save.
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useTemperatureStore } from "../../stores/temperatureStore";
import type { SensorColorsSetting } from "../types/SensorColorsSetting";

const props = defineProps<{ setting: SensorColorsSetting }>();

const temperatureStore = useTemperatureStore();
const { sensors } = storeToRefs(temperatureStore);

const SENSOR_NAME = /^[a-z][a-z0-9_-]{0,40}$/;
const sensorNames = computed(() => Object.keys(sensors.value || {}).filter((n) => SENSOR_NAME.test(n)));

const colorOf = (name: string) => temperatureStore.colorFor(name);

function onChange(name: string, event: Event) {
  const hex = (event.target as HTMLInputElement | null)?.value;
  if (hex) void props.setting.setColor(name, hex);
}
</script>

<template>
  <div class="w-full">
    <p v-if="sensorNames.length === 0" class="text-sm text-gray-500 italic">
      No sensors reported yet — open the dashboard to populate the sensor list.
    </p>
    <ul v-else class="divide-y divide-gray-700 rounded border border-gray-700 overflow-hidden">
      <li
          v-for="name in sensorNames"
          :key="name"
          class="flex items-center justify-between gap-6 px-3 py-2 bg-gray-800/50"
      >
        <div class="flex items-center space-x-3">
          <span
              class="inline-block w-4 h-4 rounded-full border border-gray-600"
              :style="{ backgroundColor: colorOf(name) }"
          ></span>
          <span class="font-mono text-sm text-gray-100 uppercase">{{ name }}</span>
        </div>
        <label class="flex items-center space-x-2">
          <input
              type="color"
              :value="colorOf(name)"
              class="w-10 h-8 bg-gray-900 border border-gray-600 rounded cursor-pointer"
              :aria-label="`${name} colour`"
              :data-testid="`setting-${setting.key}-${name}`"
              @change="(e) => onChange(name, e)"
          >
          <span class="text-xs text-gray-400 font-mono">{{ colorOf(name) }}</span>
        </label>
      </li>
    </ul>
  </div>
</template>
