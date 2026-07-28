<script setup>
// Temperature module settings panel. Renders a global unit
// dropdown plus one colour-swatch row per sensor. All persistence
// lives in the module store.
//
// Reference: ``.agent/contracts/frontend-module.md`` § 4
// (ModuleContext.settings gives a typed settings client).

import { storeToRefs } from 'pinia'
import { useTemperatureStore } from '../store.js'

const store = useTemperatureStore()
const { sensors, unit, sensorColors } = storeToRefs(store)

const SENSOR_NAME_PATTERN = /^[a-z][a-z0-9_-]{0,40}$/
function isSensorName(name) {
  return typeof name === 'string' && SENSOR_NAME_PATTERN.test(name)
}

const sensorList = () => {
  const list = []
  for (const name of Object.keys(sensors.value || {})) {
    if (isSensorName(name)) list.push(name)
  }
  return list
}

function onColorChange(name, event) {
  const hex = event?.target?.value
  if (!hex) return
  store.setSensorColor(name, hex)
}
</script>

<template>
  <div class="space-y-6">
    <!-- Global unit toggle -->
    <section class="space-y-2">
      <header>
        <h3 class="text-sm font-semibold uppercase tracking-wider text-gray-300">
          Display unit
        </h3>
        <p class="text-xs text-gray-400 mt-1">
          Switches the chart Y-axis and the control-box labels
          between Celsius and Kelvin. The backend keeps storing
          everything in °C — conversion (K = °C + 273.15) is
          display-only.
        </p>
      </header>
      <div class="flex items-center space-x-2">
        <select
          :value="unit"
          @change="(e) => store.setUnit(e.target.value)"
          class="bg-gray-900 border border-gray-600 rounded px-3 py-2 text-gray-100 font-mono text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="celsius">Celsius (°C)</option>
          <option value="kelvin">Kelvin (K)</option>
        </select>
        <span class="text-xs text-gray-500">
          Persists via
          <code class="bg-gray-700 px-1 py-0.5 rounded">PUT .../settings/unit</code>.
        </span>
      </div>
    </section>

    <!-- Per-sensor colour swatches -->
    <section class="space-y-2">
      <header>
        <h3 class="text-sm font-semibold uppercase tracking-wider text-gray-300">
          Per-sensor colours
        </h3>
        <p class="text-xs text-gray-400 mt-1">
          Choose the chart series + control-box swatch colour for
          each sensor. Changes persist via
          <code class="bg-gray-700 px-1 py-0.5 rounded">PUT .../settings/sensor_colors</code>
          and propagate to the chart on the next render.
        </p>
      </header>

      <div v-if="sensorList().length === 0" class="text-sm text-gray-500 italic">
        No sensors reported yet — open the dashboard to populate the
        sensor list.
      </div>

      <ul
        v-else
        class="divide-y divide-gray-700 rounded border border-gray-700 overflow-hidden"
      >
        <li
          v-for="name in sensorList()"
          :key="name"
          class="flex items-center justify-between px-3 py-2 bg-gray-800/50"
        >
          <div class="flex items-center space-x-3">
            <span
              class="inline-block w-4 h-4 rounded-full border border-gray-600"
              :style="{ backgroundColor: sensorColors[name] || '#A855F7' }"
            ></span>
            <span class="font-mono text-sm text-gray-100 uppercase">{{ name }}</span>
          </div>
          <label class="flex items-center space-x-2">
            <input
              type="color"
              :value="sensorColors[name] || '#A855F7'"
              @input="(e) => onColorChange(name, e)"
              class="w-10 h-8 bg-gray-900 border border-gray-600 rounded cursor-pointer"
              :aria-label="`${name} colour`"
            >
            <span class="text-xs text-gray-400 font-mono">
              {{ sensorColors[name] || '#A855F7' }}
            </span>
          </label>
        </li>
      </ul>
    </section>
  </div>
</template>
