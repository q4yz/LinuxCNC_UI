<script setup>
import { ref, computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useMachineStore } from '../stores/machine'

const store = useMachineStore()
const { status, temperatureHistory } = storeToRefs(store)

const inputTemp = ref(0)

const setTemp = () => {
  store.setTargetTemperature(inputTemp.value)
}

const turnOff = () => {
  inputTemp.value = 0
  store.setTargetTemperature(0)
}

// Chart Options Computation
const chartOptions = computed(() => {
  return {
    animation: false, // Critical for high-frequency 10Hz data
    tooltip: {
      trigger: 'axis'
    },
    legend: {
      data: ['Target', 'Actual'],
      textStyle: { color: '#D1D5DB' }
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: temperatureHistory.value.map(item => item.time),
      axisLabel: { color: '#9CA3AF' }
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#9CA3AF' },
      splitLine: { lineStyle: { color: '#374151' } },
      min: 0,
      max: (value) => Math.max(value.max + 10, 50)
    },
    series: [
      {
        name: 'Target',
        type: 'line',
        data: temperatureHistory.value.map(item => item.target),
        itemStyle: { color: '#EF4444' }, // Tailwind red-500
        lineStyle: { type: 'dashed', width: 2 },
        symbol: 'none'
      },
      {
        name: 'Actual',
        type: 'line',
        data: temperatureHistory.value.map(item => item.actual),
        itemStyle: { color: '#3B82F6' }, // Tailwind blue-500
        lineStyle: { width: 3 },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [{
              offset: 0, color: 'rgba(59, 130, 246, 0.4)'
            }, {
              offset: 1, color: 'rgba(59, 130, 246, 0.05)'
            }]
          }
        },
        symbol: 'none'
      }
    ]
  }
})
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden mt-6 flex flex-col">
    <!-- Header & Controls -->
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex flex-wrap gap-4 items-center justify-between">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center">
        <span class="mr-2">🔥</span> Heater
      </h2>
      
      <!-- Temperature Readouts -->
      <div class="flex space-x-6 text-sm">
        <div class="flex flex-col">
          <span class="text-gray-400 text-xs">Actual</span>
          <span class="font-mono text-xl font-bold text-blue-400">{{ status.actual_temp?.toFixed(1) || '0.0' }}°C</span>
        </div>
        <div class="flex flex-col">
          <span class="text-gray-400 text-xs">Target</span>
          <span class="font-mono text-xl font-bold text-red-400">{{ status.target_temp?.toFixed(1) || '0.0' }}°C</span>
        </div>
      </div>
      
      <!-- Controls -->
      <div class="flex items-center space-x-2">
        <input 
          v-model="inputTemp" 
          type="number" 
          class="w-20 bg-gray-900 border border-gray-600 rounded px-2 py-1 text-gray-100 font-mono text-right focus:outline-none focus:border-blue-500"
          @keyup.enter="setTemp"
        >
        <span class="text-gray-400">°C</span>
        
        <button 
          @click="setTemp"
          class="px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded font-semibold transition-colors"
        >
          Set
        </button>
        <button 
          @click="turnOff"
          class="px-3 py-1 bg-gray-600 hover:bg-gray-500 text-white rounded font-semibold transition-colors"
        >
          Off
        </button>
      </div>
    </div>
    
    <!-- ECharts Container -->
    <div class="p-4 w-full h-64 mt-4 relative">
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
