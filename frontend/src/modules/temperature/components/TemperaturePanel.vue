<script setup>
// Temperature panel — migrated from the legacy components/ folder
// into the temperature module per issue #32 /
// MODULE_SYSTEM_ISSUE_03_TEMPERATURE_MIGRATION.md.
//
// Issue #35 changes (vs. the original migration):
//
//   * Fixed 30 s chart window driven by a single computed
//     ``chartOptions``; the legacy
//     ``history_window_seconds`` / ``history_poll_interval_ms`` knobs
//     are gone from the backend ``TemperatureSettings``.
//   * Per-sensor visibility toggle (eye icon) sourced from
//     ``store.visibleSensors``.
//   * Per-sensor colour (control box swatch + chart series) sourced
//     from ``store.sensorColors``.
//   * Cubic interpolation + deterministic jitter on the chart so
//     1 s REST samples render as a flowing curve rather than a
//     staircase.
//   * Global unit toggle (°C / K) below — converts
//     ``displayTemp`` value only; the raw °C value the backend
//     delivers is untouched.
//   * Rounded-to-two-decimals labels everywhere.
//
// Reference: .agent/contracts/frontend-module.md § 6 (frozen
// telemetry payloads — we clone before storing, see store.js).

import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useTemperatureStore } from '../store.js'

const store = useTemperatureStore()
const {
  history,
  sensors,
  unit,
  visibleSensors,
  sensorColors,
} = storeToRefs(store)

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

// Issue #35 § 6: noise generator. The sin hash is the GLSL canonical
// pseudo-noise — keyed on the integer tick index so the jitter is
// stable between re-renders and the line never flickers.
function jitterFor(i) {
  const x = Math.sin(i * 12.9898) * 43758.5453
  return (x - Math.floor(x)) - 0.5 // range [-0.5, 0.5]
}

function smoothstep(u) {
  // Hermite smoothstep ``u*u*(3 - 2*u)`` — C1-continuous at the
  // segment endpoints and avoids the cusp that linear interpolation
  // produces on a 1 s × 1 °C sample grid.
  return u * u * (3 - 2 * u)
}

function roundTo(value, decimals) {
  if (!Number.isFinite(value)) return 0
  const factor = Math.pow(10, decimals)
  return Math.round(value * factor) / factor
}

/**
 * Build a 30-step series for ``name`` (sensor) and ``key``
 * (``"actual"`` or ``"target"``). Backfills / zero-fills /
 * interpolates between the raw history points per issue #35 § 5.2.
 *
 * The returned values are in Celsius. The unit conversion happens
 * on the way into the chart label so the same interpolation can be
 * reused regardless of toggle.
 */
function interpolateSeries(sensorName, key, buffer, ticks) {
  // Pre-build the (timestamp, value) pairs we know about. Values
  // that are null / undefined are rendered as 0 per the issue's
  // zero-fill policy; we don't drop them, so the backfill below
  // still sees the sample.
  const samples = []
  for (const point of buffer) {
    const raw = point?.sensors?.[sensorName]
    if (!raw) continue
    const value = raw[key]
    // Null/undefined → 0 — see § 2.4 / § 5.2 of the issue.
    samples.push({ timestamp: point.timestamp, value: Number.isFinite(value) ? value : 0 })
  }

  // If we have *no* samples yet, return the all-zero trace so the
  // chart isn't empty before the first poll lands.
  if (samples.length === 0) {
    return ticks.map(() => 0)
  }

  const firstValue = samples[0].value
  const series = []
  for (let i = 0; i < ticks.length; i++) {
    // Tick index (``i``) is the stable noise key — keyed on the
    // integer index, not the absolute timestamp, so the rendered
    // pixels don't flicker when the chart rerenders moments later.
    const ts = ticks[i]
    const noise = jitterFor(i) * 0.1
    if (ts < samples[0].timestamp) {
      // First-sample back-fill: pre-first-sample ticks use the
      // very first sample's value so the curve appears to "start"
      // from the first reading rather than from zero.
      series.push(firstValue + noise)
      continue
    }
    // Find the bracketing samples (most recent strictly <= ts,
    // earliest strictly >= ts).
    let lo = null
    let hi = null
    for (let k = 0; k < samples.length; k++) {
      if (samples[k].timestamp <= ts) lo = samples[k]
      if (samples[k].timestamp >= ts && hi === null) hi = samples[k]
    }
    if (lo && hi && lo !== hi) {
      const span = hi.timestamp - lo.timestamp
      const u = span > 0 ? (ts - lo.timestamp) / span : 0
      const smooth = smoothstep(u)
      const base = lo.value + (hi.value - lo.value) * smooth
      series.push(base + noise)
    } else if (lo && (!hi || hi === lo)) {
      // Past-the-last-sample: hold last value with a touch of jitter
      // so the line doesn't dead-end at the right edge.
      series.push(lo.value + jitterFor(i) * 0.05)
    } else if (hi) {
      // Before the first sample (shouldn't normally happen given
      // the early branch, but be defensive).
      series.push(hi.value)
    } else {
      series.push(0)
    }
  }
  return series
}

// Tweakable interpolation knobs — exposed as constants rather than
// store state to keep the issue's scope tight. A future revision
// can graduate these into settings.
const WINDOW_SECONDS = 30

/**
 * Build the ECharts options object. Single source of truth for the
 * chart's rendering pipeline so unit / visibility / colour toggles
 * recompute together.
 */
const chartOptions = computed(() => {
  const legendData = []
  const series = []
  const temps = sensors.value || {}
  const buffer = history.value || []
  const visibility = visibleSensors.value || {}

  // Anchor ticks to "now" so the window is always the *last*
  // 30 seconds, independent of when the dashboard was rendered.
  const now = Date.now()
  const ticks = []
  const tickLabels = []
  for (let i = WINDOW_SECONDS - 1; i >= 0; i--) {
    const ts = now - i * 1000
    const d = new Date(ts)
    const pad = (n) => n.toString().padStart(2, '0')
    const cents = Math.floor((d.getTime() % 1000) / 10)
    ticks.push(ts)
    tickLabels.push(
      `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(
        d.getSeconds(),
      )}.${cents.toString().padStart(2, '0')}`,
    )
  }

  Object.keys(temps).forEach((sensorName) => {
    if (visibility[sensorName] === false) return
    const color = store.colorFor(sensorName)
    const actualSeries = interpolateSeries(sensorName, 'actual', buffer, ticks)
    const targetSeries = interpolateSeries(sensorName, 'target', buffer, ticks)
    const round = (v) => roundTo(
      unit.value === 'kelvin' ? v + 273.15 : v,
      2,
    )

    legendData.push(`${sensorName} actual`)
    series.push({
      name: `${sensorName} actual`,
      type: 'line',
      data: actualSeries.map(round),
      itemStyle: { color },
      lineStyle: { width: 3 },
      symbol: 'none',
      smooth: true,
    })

    if (temps[sensorName].target !== undefined) {
      legendData.push(`${sensorName} target`)
      series.push({
        name: `${sensorName} target`,
        type: 'line',
        data: targetSeries.map(round),
        itemStyle: { color },
        lineStyle: { type: 'dashed', width: 2, opacity: 0.6 },
        symbol: 'none',
        smooth: true,
      })
    }
  })

  const unitLabel = unit.value === 'kelvin' ? 'K' : '°C'
  const axisFormatter = (value) => {
    const num = Number(value)
    if (!Number.isFinite(num)) return ''
    // round to two decimals in the active unit
    const v = unit.value === 'kelvin' ? num + 273.15 : num
    return `${roundTo(v, 2).toFixed(2)} ${unitLabel}`
  }

  return {
    animation: false,
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) =>
        `${roundTo(
          unit.value === 'kelvin' ? value + 273.15 : value,
          2,
        ).toFixed(2)} ${unitLabel}`,
    },
    legend: {
      data: legendData,
      textStyle: { color: '#D1D5DB' },
      top: 0,
    },
    grid: {
      // Issue #35 § 5.2 / § 2.8 — explicit margins so the legend and
      // the axis labels never crowd the data.
      top: 32,
      right: 24,
      bottom: 48,
      left: 64,
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: tickLabels,
      axisLabel: { color: '#9CA3AF' },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#9CA3AF', formatter: axisFormatter },
      splitLine: { lineStyle: { color: '#374151' } },
      name: unitLabel,
      nameTextStyle: { color: '#9CA3AF' },
      min: 0,
      max: (value) => Math.max(value.max + 10, 50),
    },
    series,
  }
})

// Local helper for the template — returns the rounded display
// value (active unit) without an extra computed per sensor row.
const fmtTemp = (v) => store.displayTemp(v).toFixed(2)
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden mt-6 flex flex-col">
    <!-- Header & Controls -->
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex items-center">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        <span class="mr-2">🔥</span> Temperatures
      </h2>
    </div>

    <!-- Global unit toggle (°C / K). Sits above the per-sensor rows
         so the operator can flip the entire module between Celsius
         and Kelvin in one click. -->
    <div class="px-4 pt-3 pb-1 border-b border-gray-700 bg-gray-700/20 flex items-center space-x-2">
      <span class="text-xs uppercase text-gray-400 tracking-wider">Unit</span>
      <select
        :value="unit"
        @change="(e) => store.setUnit(e.target.value)"
        class="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-gray-100 font-mono text-xs focus:outline-none focus:border-blue-500"
      >
        <option value="celsius">°C</option>
        <option value="kelvin">K</option>
      </select>
    </div>

    <div class="p-4 bg-gray-700/20 border-b border-gray-600 flex flex-wrap gap-4 items-start">
      <div
        v-for="(data, name) in sensors"
        :key="name"
        class="bg-gray-800 border border-gray-600 rounded-lg p-3 flex flex-col space-y-2 min-w-[200px] shadow-sm"
      >
        <div class="flex justify-between items-center">
          <span class="font-semibold text-gray-300 uppercase text-xs flex items-center space-x-2">
            <!-- Coloured swatch matches the chart series colour -->
            <span
              class="inline-block w-3 h-3 rounded-full"
              :style="{ backgroundColor: store.colorFor(name) }"
              :aria-label="`${name} colour swatch`"
            ></span>
            <span>{{ name }}</span>
          </span>
          <span
            class="font-mono text-lg font-bold"
            :class="data.target !== undefined ? 'text-blue-400' : 'text-green-400'"
          >
            {{ fmtTemp(data.actual) }}{{ unit === 'kelvin' ? 'K' : '°C' }}
          </span>
        </div>

        <div class="flex justify-between items-center -mt-1">
          <!-- Eye-icon toggle: hides the chart series but keeps the
               control box row visible so the operator can still set
               targets. -->
          <button
            type="button"
            @click="store.toggleSensorVisibility(name)"
            :title="
              (visibleSensors[name] === false ? 'Show' : 'Hide') +
              ' ' + name + ' on chart'
            "
            :aria-pressed="visibleSensors[name] !== false"
            class="text-gray-300 hover:text-white text-xs px-2 py-1 rounded border border-gray-600 hover:border-gray-400 bg-gray-900/50"
          >
            <span v-if="visibleSensors[name] !== false">👁</span>
            <span v-else>🚫</span>
            <span class="ml-1 align-middle">
              {{ visibleSensors[name] === false ? 'Hidden' : 'Visible' }}
            </span>
          </button>
        </div>

        <div v-if="data.target !== undefined" class="flex flex-col space-y-2 pt-2 border-t border-gray-700">
          <div class="flex justify-between items-center">
            <span class="text-gray-400 text-xs">Target:</span>
            <span class="font-mono text-sm text-red-400">
              {{ fmtTemp(data.target) }}{{ unit === 'kelvin' ? 'K' : '°C' }}
            </span>
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
