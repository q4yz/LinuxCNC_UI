<script setup>
// Temperature panel — migrated from the legacy components/ folder
// into the temperature module per issue #32 /
// MODULE_SYSTEM_ISSUE_03_TEMPERATURE_MIGRATION.md.
//
// Changes vs. the legacy component:
//
//   * ``useMachineStore`` → ``useTemperatureStore`` (the module's
//     own Pinia store under the ``module_temperature`` id).
//   * ``MachineStateService.setTargetTemperature(...)`` →
//     ``fetch('/api/v1/modules/temperature/sensors/.../target', ...)``
//     hand-written. We deliberately avoid the generated OpenAPI
//     client because the temperature module's router is mounted
//     after the generator may have last run; a raw fetch keeps the
//     panel working even if ``frontend/generated/api/`` is stale.
//   * ``temperatureHistory`` → ``store.history``. The store owns
//     the rolling window and the 1 s polling cadence.
//
// Reference: .agent/contracts/frontend-module.md § 6 (frozen
// telemetry payloads — we clone before storing, see store.js).

import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useTemperatureStore } from '../store.js'

const store = useTemperatureStore()
const { history, sensors } = storeToRefs(store)

// Per-sensor target input boxes. Held locally so the user can edit
// without immediately firing a backend mutation on every keystroke.
const inputTemps = ref({})

/**
 * Issue a ``POST /api/v1/modules/temperature/sensors/{name}/target``
 * with the user-entered value. Errors are logged but never re-thrown
 * to the UI — the operator can retry by editing the input.
 */
async function postTarget(name, target) {
  const res = await fetch(
    `/api/v1/modules/temperature/sensors/${encodeURIComponent(name)}/target`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sensor_name: name, target }),
    },
  )
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText)
    throw new Error(`set target failed: ${res.status} ${detail}`)
  }
  return res.json()
}

const setTemp = async (name) => {
  const raw = inputTemps.value[name]
  const t = parseFloat(raw || 0)
  try {
    await postTarget(name, t)
  } catch (e) {
    // eslint-disable-next-line no-console
    console.error('Failed to set temperature', e)
  }
}

const turnOff = async (name) => {
  inputTemps.value[name] = 0
  try {
    await postTarget(name, 0)
  } catch (e) {
    // eslint-disable-next-line no-console
    console.error('Failed to turn off temperature for', name, e)
  }
}

// Chart options built from the store's rolling history. Same shape as
// the legacy component so the pixel-for-pixel spot-check in the
// issue's § 6.5 still applies.
const chartOptions = computed(() => {
  const legendData = []
  const series = []

  const colors = {
    extruder: '#EF4444', // Red
    bed: '#3B82F6',      // Blue
    cpu: '#10B981',      // Green
  }

  const temps = sensors.value || {}

  Object.keys(temps).forEach((key) => {
    const color = colors[key] || '#A855F7'

    // Actual series (solid line)
    legendData.push(`${key} actual`)
    series.push({
      name: `${key} actual`,
      type: 'line',
      data: history.value.map((item) => item.sensors?.[key]?.actual || 0),
      itemStyle: { color: color },
      lineStyle: { width: 3 },
      symbol: 'none',
    })

    // Target series (dashed line)
    if (temps[key].target !== undefined) {
      legendData.push(`${key} target`)
      series.push({
        name: `${key} target`,
        type: 'line',
        data: history.value.map((item) => item.sensors?.[key]?.target || 0),
        itemStyle: { color: color },
        lineStyle: { type: 'dashed', width: 2, opacity: 0.6 },
        symbol: 'none',
      })
    }
  })

  return {
    animation: false, // Critical for high-frequency 10Hz data
    tooltip: { trigger: 'axis' },
    legend: {
      data: legendData,
      textStyle: { color: '#D1D5DB' },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: history.value.map((item) => item.time),
      axisLabel: { color: '#9CA3AF' },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#9CA3AF' },
      splitLine: { lineStyle: { color: '#374151' } },
      min: 0,
      max: (value) => Math.max(value.max + 10, 50),
    },
    series,
  }
})
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden mt-6 flex flex-col">
    <!-- Header & Controls -->
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex items-center">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        <span class="mr-2">🔥</span> Temperatures
      </h2>
    </div>

    <div class="p-4 bg-gray-700/20 border-b border-gray-600 flex flex-wrap gap-4 items-start">
      <div
        v-for="(data, name) in sensors"
        :key="name"
        class="bg-gray-800 border border-gray-600 rounded-lg p-3 flex flex-col space-y-2 min-w-[200px] shadow-sm"
      >
        <div class="flex justify-between items-center">
          <span class="font-semibold text-gray-300 uppercase text-xs">{{ name }}</span>
          <span class="font-mono text-lg font-bold" :class="data.target !== undefined ? 'text-blue-400' : 'text-green-400'">
            {{ data.actual?.toFixed(1) || '0.0' }}°C
          </span>
        </div>

        <div v-if="data.target !== undefined" class="flex flex-col space-y-2 pt-2 border-t border-gray-700">
          <div class="flex justify-between items-center">
            <span class="text-gray-400 text-xs">Target:</span>
            <span class="font-mono text-sm text-red-400">{{ data.target?.toFixed(1) || '0.0' }}°C</span>
          </div>
          <div class="flex items-center space-x-2">
            <input
              v-model="inputTemps[name]"
              type="number"
              class="w-16 bg-gray-900 border border-gray-600 rounded px-2 py-1 text-gray-100 font-mono text-xs text-right focus:outline-none focus:border-blue-500"
              @keyup.enter="setTemp(name)"
            >
            <button
              @click="setTemp(name)"
              class="px-2 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-semibold transition-colors flex-1"
            >
              Set
            </button>
            <button
              @click="turnOff(name)"
              class="px-2 py-1 bg-gray-600 hover:bg-gray-500 text-white rounded text-xs font-semibold transition-colors"
            >
              Off
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ECharts Container -->
    <div class="p-4 w-full h-64 relative">
      <v-chart class="chart" :option="chartOptions" autoresize />
    </div>
  </div>
</template>

<style scoped>
.chart {
  width: 100%;
  height: 100%;
  min-height: 250px;
}
</style>
