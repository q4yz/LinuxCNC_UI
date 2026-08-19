<script setup lang="ts">
// Temperature panel — chart + per-row controls for every
// controllable heater and every read-only sensor.

import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useTemperatureStore } from '../store'
import {HeaterControlRequest} from "../../../entities/tools/Heater";
import {TemperatureUnit} from "../../../entities";


const store = useTemperatureStore()

const currentTime = ref<number>(Date.now())
let animFrame: number | null = null

onMounted(() => {
  store.start()

  const tick = () => {
    currentTime.value = Date.now()
    animFrame = requestAnimationFrame(tick)
  }
  animFrame = requestAnimationFrame(tick)
})

onBeforeUnmount(() => {
  store.stop()
  if (animFrame !== null) cancelAnimationFrame(animFrame)
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
  const promises: Promise<any>[] = []
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

const chartOptions = computed(() => {
  const now = currentTime.value
  const renderTime = now - 1000

  const legendData: string[] = []
  const series: any[] = []
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

  const unitLabel =  store.unit === TemperatureUnit.KELVIN ? 'K' : '°C'
  const axisFormatter = (value: any) => {
    const num = Number(value)
    if (!Number.isFinite(num)) return ''
    const v =  store.unit ===TemperatureUnit.KELVIN ? num + 273.15 : num
    return `${roundTo(v, 2).toFixed(2)} ${unitLabel}`
  }

  return {
    animation: false,
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: any) =>
          `${roundTo(store.unit === TemperatureUnit.KELVIN ? Number(value) + 273.15 : Number(value), 2).toFixed(2)} ${unitLabel}`,
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
        formatter: (value: any) => {
          const d = new Date(value)
          const pad = (n: number) => n.toString().padStart(2, '0')
          return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
        }
      },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#9CA3AF', formatter: axisFormatter },
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
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden mt-6 flex flex-col ">
    <!-- Header & Controls -->
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex items-center">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        <span class="mr-2">🔥</span> Temperatures
      </h2>
    </div>

    <!-- Global unit toggle and Cool All -->
    <div class="px-4 py-3 border-b border-gray-700 bg-gray-700/20 flex items-center justify-between">

      <div class="flex items-center space-x-2">
        <span class="text-xs uppercase text-gray-400 tracking-wider font-bold">Unit</span>
        <select
            :value="unit"
            @change="(e) => store.setUnit((e.target as HTMLSelectElement).value as any)"
            class="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-gray-100 font-mono text-xs focus:outline-none focus:border-blue-500"
        >
          <option :value="TemperatureUnit.CELSIUS">°C</option>
          <option :value="TemperatureUnit.KELVIN">K</option>
        </select>
      </div>

      <div class="flex items-center space-x-2">
        <span class="text-xs uppercase text-gray-400 tracking-wider font-bold">Cool</span>
        <button
            type="button"
            @click="turnOffAll"
            title="Turn off all heaters"
            class="text-blue-300 hover:text-white text-xs px-3 py-1 rounded border border-blue-800 hover:border-blue-500 bg-blue-900/30 flex items-center space-x-1 shrink-0 transition-colors shadow-sm"
        >
          <span>❄️ All</span>
        </button>
      </div>

    </div>

    <!-- Reading Rows -->
    <div class="p-3 sm:p-4 bg-gray-700/20 border-b border-gray-600 flex flex-col space-y-2">
      <div
          v-for="(data, name) in sensors"
          :key="name"
          class="bg-gray-800 border border-gray-600 rounded-lg p-2 sm:p-3 flex flex-row items-center justify-between shadow-sm gap-1 "
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
              <input
                  v-model="inputTemps[name]"
                  type="number"
                  class="w-12 sm:w-16 bg-gray-900 border border-gray-600 rounded px-1 sm:px-2 py-1 text-gray-100 font-mono text-xs text-right focus:outline-none focus:border-blue-500"
                  @keyup.enter="setTemp(String(name))"
              >
              <button
                  type="button"
                  @click="setTemp(String(name))"
                  class="px-2 sm:px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-semibold transition-colors"
              >
                Set
              </button>
              <button
                  type="button"
                  @click="turnOff(String(name))"
                  class="hidden lg:block px-3 py-1 bg-gray-600 hover:bg-gray-500 text-white rounded text-xs font-semibold transition-colors"
              >
                Off
              </button>
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

input[type=number]::-webkit-inner-spin-button,
input[type=number]::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
input[type=number] {
  -moz-appearance: textfield;
}
</style>