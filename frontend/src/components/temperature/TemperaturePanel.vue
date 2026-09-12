<script setup lang="ts">
// Temperature panel — chart + per-row controls for every
// controllable heater and every read-only sensor.

import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useTemperatureStore } from '../../stores/temperatureStore'
import {HeaterControlRequest} from "../../entities/tools/Heater";
import {TemperatureUnit, isTemperatureUnit} from "../../entities";
import { BaseButton } from '../../ui/index.ts'
import BaseCard from '../../ui/BaseCard.vue'
import BaseInput from '../../ui/BaseInput.vue'
import BaseSelect from '../../ui/BaseSelect.vue'


const store = useTemperatureStore()

// Redraw cadence for the chart's "now" cursor. The underlying
// samples only land at 1 Hz (temperatureStore's own poll), but
// ticking currentTime faster than that lets the smoothstep
// interpolation below animate the curve between samples instead of
// jumping once a second. 10 Hz looks smooth to the eye while
// costing a fraction of what a 60 Hz requestAnimationFrame loop
// did — rebuilding the whole ECharts option is not free, and on a
// GPU-less Pi 4 that 6x reduction is the difference between a
// warm CPU and a pegged one.
const CHART_TICK_MS = 100
const currentTime = ref<number>(Date.now())
let tickHandle: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  store.start()
  currentTime.value = Date.now()
  tickHandle = setInterval(() => {
    currentTime.value = Date.now()
  }, CHART_TICK_MS)
})

onBeforeUnmount(() => {
  store.stop()
  if (tickHandle !== null) clearInterval(tickHandle)
})

const {
  history,
  sensors,
  unit,
  visibleSensors,
} = storeToRefs(store)

const inputTemps = ref<Record<string, string | number>>({})

async function postTarget(toolId: string, target: number) {
  // Routes through the updated store action using the HeaterControlRequest DTO
  const request: HeaterControlRequest = new HeaterControlRequest({ toolId, target })
  const result = await store.setTarget(request)
  if (result && result.failed) {
    throw new Error(result.failureReason || 'set target failed')
  }
  return result
}

const setTemp = async (name: string) => {
  const raw = inputTemps.value[name]
  const t = parseFloat(String(raw || 0))
  try {
    await postTarget(name, t)
  } catch (e) {
    console.error('Failed to set temperature', e)
  }
}

const turnOff = async (name: string) => {
  inputTemps.value[name] = 0
  try {
    await postTarget(name, 0)
  } catch (e) {
    console.error('Failed to turn off temperature for', name, e)
  }
}

const turnOffAll = async () => {
  const promises: Promise<void>[] = []
  for (const [name, data] of Object.entries(sensors.value)) {
    if (data.target !== undefined) {
      promises.push(turnOff(name))
    }
  }
  await Promise.all(promises)
}

function smoothstep(u: number): number {
  return u * u * (3 - 2 * u)
}

function roundTo(value: number, decimals: number): number {
  if (!Number.isFinite(value)) return 0
  const factor = Math.pow(10, decimals)
  return Math.round(value * factor) / factor
}

const WINDOW_SECONDS = 30

// Formatter callbacks are handed to ECharts by reference and only
// ever invoked at render time, so they are declared once here
// instead of as inline closures inside ``chartOptions`` — at 10 Hz
// that avoids allocating a fresh closure (and capturing
// ``unitLabel``) on every single tick for no behavioural gain.
function unitLabelFor(unit: TemperatureUnit): string {
  return unit === TemperatureUnit.KELVIN ? 'K' : '°C'
}

function yAxisLabelFormatter(value: number | string): string {
  const num = Number(value)
  if (!Number.isFinite(num)) return ''
  const v = store.unit === TemperatureUnit.KELVIN ? num + 273.15 : num
  return `${roundTo(v, 2).toFixed(2)} ${unitLabelFor(store.unit)}`
}

function tooltipValueFormatter(value: number | string): string {
  const num = Number(value)
  const v = store.unit === TemperatureUnit.KELVIN ? num + 273.15 : num
  return `${roundTo(v, 2).toFixed(2)} ${unitLabelFor(store.unit)}`
}

function xAxisLabelFormatter(value: number | string): string {
  const d = new Date(value)
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

const chartOptions = computed(() => {
  const now = currentTime.value
  const renderTime = now - 1000

  const legendData: string[] = []
  const series: Record<string, unknown>[] = []
  const temps = sensors.value || {}
  const buffer = history.value || []
  const visibility = visibleSensors.value || {}

  Object.keys(temps).forEach((sensorName) => {
    if (visibility[sensorName] === false) return
    const color = store.colorFor(sensorName)
    const round = (v: number) => roundTo( store.unit === TemperatureUnit.KELVIN ? v + 273.15 : v, 2)

    const actualSamples: { ts: number; val: number }[] = []
    const targetSamples: { ts: number; val: number }[] = []
    for (const point of buffer) {
      const raw = point?.sensors?.[sensorName]
      if (!raw) continue
      if (Number.isFinite(raw.actual)) actualSamples.push({ ts: point.timestamp, val: raw.actual })
      if (Number.isFinite(raw.target)) targetSamples.push({ ts: point.timestamp, val: raw.target! })
    }

    // Build the Actual curve.
    const actualData: [number, number][] = []
    let lastActualPt: { ts: number; val: number } | null = null

    for (let i = 0; i < actualSamples.length; i++) {
      const pt = actualSamples[i]
      if (pt.ts <= renderTime) {
        actualData.push([pt.ts, round(pt.val)])
        lastActualPt = pt
      } else {
        if (lastActualPt) {
          const span = pt.ts - lastActualPt.ts
          const u = span > 0 ? (renderTime - lastActualPt.ts) / span : 0
          const smooth_u = smoothstep(Math.max(0, Math.min(u, 1)))
          const interp = lastActualPt.val + (pt.val - lastActualPt.val) * smooth_u
          actualData.push([renderTime, round(interp)])
        }
        break
      }
    }

    if (actualData.length > 0 && actualData[actualData.length - 1][0] < renderTime) {
      actualData.push([renderTime, actualData[actualData.length - 1][1]])
    }

    legendData.push(`${sensorName}`)
    series.push({
      name: `${sensorName}`,
      type: 'line',
      data: actualData,
      itemStyle: { color },
      lineStyle: { width: 3 },
      symbol: 'none',
      smooth: true,
    })

    // Target curve: step interpolation, only renders if the row is a controllable heater
    if (temps[sensorName].target !== undefined) {
      const targetData: [number, number][] = []
      for (let i = 0; i < targetSamples.length; i++) {
        const pt = targetSamples[i]
        if (pt.ts <= renderTime) {
          targetData.push([pt.ts, round(pt.val)])
        } else {
          break
        }
      }

      if (targetData.length > 0 && targetData[targetData.length - 1][0] < renderTime) {
        targetData.push([renderTime, targetData[targetData.length - 1][1]])
      }

      series.push({
        name: `${sensorName} target`,
        type: 'line',
        step: 'end',
        data: targetData,
        itemStyle: { color },
        lineStyle: { type: 'dashed', width: 2, opacity: 0.6 },
        symbol: 'none',
        smooth: false,
        areaStyle: { opacity: 0.1 },
      })
    }
  })

  const unitLabel = unitLabelFor(store.unit)

  return {
    animation: false,
    tooltip: {
      trigger: 'axis',
      valueFormatter: tooltipValueFormatter,
    },
    legend: {
      data: legendData,
      textStyle: { color: '#D1D5DB' },
      top: 0,
    },
    grid: {
      top: 32, right: 24, bottom: 48, left: 64, containLabel: false,
    },
    xAxis: {
      type: 'time',
      boundaryGap: false,
      min: renderTime - (WINDOW_SECONDS - 1) * 1000,
      max: renderTime,
      minInterval: 10000,
      axisLabel: {
        color: '#9CA3AF',
        formatter: xAxisLabelFormatter,
      },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#9CA3AF', formatter: yAxisLabelFormatter },
      splitLine: { lineStyle: { color: '#374151' } },
      name: unitLabel,
      nameTextStyle: { color: '#9CA3AF' },
      min: 0,
      max: (value: { max: number }) => Math.max(value.max + 10, 50),
    },
    series,
  }
})

const fmtTemp = (v: number | null | undefined) => store.displayTemp(v).toFixed(2)
</script>

<template>
  <BaseCard title="🔥 Temperatures" >
    <!-- Global unit toggle and Cool All -->
    <div class="mb-3 flex items-center justify-between">

      <div class="flex items-center space-x-2">
        <span class="text-xs uppercase text-gray-400 tracking-wider font-bold">Unit</span>
        <BaseSelect
            :model-value="unit"
            @update:model-value="(v) => { if (isTemperatureUnit(v)) store.setUnit(v) }"
        >
          <option :value="TemperatureUnit.CELSIUS">°C</option>
          <option :value="TemperatureUnit.KELVIN">K</option>
        </BaseSelect>
      </div>

      <div class="flex items-center space-x-2">
        <span class="text-xs uppercase text-gray-400 tracking-wider font-bold">Cool</span>
        <BaseButton
            variant="secondary"
            size="sm"
            title="Turn off all heaters"
            @click="turnOffAll"
        >
          <span>❄️ All</span>
        </BaseButton>
      </div>

    </div>

    <!-- Reading Rows -->
    <div class="flex flex-col space-y-2">
      <div
          v-for="(data, name) in sensors"
          :key="name"
          class="bg-gray-800 border border-gray-600 rounded-lg p-2 sm:p-3 flex flex-row items-center justify-between gap-1 "
      >
        <!-- Left Side: Color, Name, and Actual Temp -->
        <div class="flex items-center space-x-2 sm:space-x-4 lg:space-x-6">
          <span class="font-semibold text-gray-300 uppercase text-xs flex items-center space-x-2 sm:w-24 lg:w-28">
            <!-- Color Swatch (Always visible) -->
            <span
                class="inline-block w-3 h-3 rounded-full shrink-0"
                :style="{ backgroundColor: store.colorFor(String(name)) }"
                :aria-label="`${name} colour swatch`"
            ></span>
            <!-- Name (Hides on smallest screens) -->
            <span class="truncate hidden sm:inline-block">{{ name }}</span>
          </span>

          <!-- Actual Temp (Always visible) -->
          <span
              class="font-mono text-base sm:text-lg font-bold whitespace-nowrap min-w-[60px] sm:min-w-[80px]"
              :class="data.target !== undefined ? 'text-blue-400' : 'text-green-400'"
          >
            {{ fmtTemp(data.actual) }}{{ unit === TemperatureUnit.KELVIN ? 'K' : '°C' }}
          </span>
        </div>

        <!-- Right Side: Target Controls & Visibility -->
        <div class="flex items-center space-x-2 sm:space-x-4">

          <!-- Target Controls (heaters only) -->
          <div v-if="data.target !== undefined" class="flex items-center space-x-2 sm:space-x-3 pr-2 sm:pr-4 border-r border-gray-700">

            <!-- Current Target Display -->
            <div class="hidden md:flex flex-col items-end justify-center mr-2">
              <span class="text-gray-500 text-[10px] uppercase tracking-wider -mb-1">Target</span>
              <span class="font-mono text-sm text-red-400 font-bold">
                {{ fmtTemp(data.target) }}{{unit === TemperatureUnit.KELVIN ? 'K' : '°C' }}
              </span>
            </div>

            <!-- Input & Buttons -->
            <div class="flex items-center space-x-1 sm:space-x-2">
              <BaseInput
                  v-model="inputTemps[name]"
                  type="number"
                  class="w-20 sm:w-24 text-right text-xs font-mono"
                  @keyup.enter="setTemp(String(name))"
              />
              <BaseButton
                  variant="primary"
                  size="sm"
                  @click="setTemp(String(name))"
              >
                Set
              </BaseButton>
              <BaseButton
                  variant="secondary"
                  size="sm"
                  class="hidden lg:block"
                  @click="turnOff(String(name))"
              >
                Off
              </BaseButton>
            </div>
          </div>

          <!-- Visibility Toggle -->
          <button
              type="button"
              @click="store.toggleSensorVisibility(String(name))"
              :title="(visibleSensors[name] === false ? 'Show' : 'Hide') + ' ' + String(name) + ' on chart'"
              :aria-pressed="visibleSensors[name] !== false"
              class="text-gray-300 hover:text-white text-xs px-2 py-1 rounded border border-gray-600 hover:border-gray-400 bg-gray-900/50 flex items-center shrink-0"
          >
            <span v-if="visibleSensors[name] !== false">👁</span>
            <span v-else>🙈</span>
          </button>

        </div>
      </div>
    </div>

    <!-- ECharts Container -->
    <div class="mt-4 w-full h-64 relative">
      <v-chart class="chart" :option="chartOptions" autoresize />
    </div>
  </BaseCard>
</template>

<style>
/* Chart + number-input styles moved to ``frontend/src/style.css`` —
 * see top-level comment in that file. The Vue ``scoped`` block was
 * triggering a UTF-8 panic in ``@tailwindcss/oxide`` 4.2.4.
 */
</style>