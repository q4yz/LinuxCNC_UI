<script setup>
import { ref, computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useMachineStore } from '../stores/machine'

const store = useMachineStore()
const { status, temperatureHistory } = storeToRefs(store)

const inputTemps = ref({})

const setTemp = (name) => {
  const t = parseFloat(inputTemps.value[name] || 0)
  store.setTargetTemperature(name, t)
}

const turnOff = (name) => {
  inputTemps.value[name] = 0
  store.setTargetTemperature(name, 0)
}

// Chart Options Computation
const chartOptions = computed(() => {
  const legendData = [];
  const series = [];

  const colors = {
    extruder: '#EF4444', // Red
    bed: '#3B82F6',      // Blue
    cpu: '#10B981',      // Green
  };

  const temps = status.value.temperatures || {};
  
  Object.keys(temps).forEach((key) => {
    const color = colors[key] || '#A855F7';
    
    // Actual series (solid line)
    legendData.push(`${key} actual`);
    series.push({
      name: `${key} actual`,
      type: 'line',
      data: temperatureHistory.value.map(item => item.sensors?.[key]?.actual || 0),
      itemStyle: { color: color },
      lineStyle: { width: 3 },
      symbol: 'none'
    });

    // Target series (dashed line)
    if (temps[key].target !== undefined) {
      legendData.push(`${key} target`);
      series.push({
        name: `${key} target`,
        type: 'line',
        data: temperatureHistory.value.map(item => item.sensors?.[key]?.target || 0),
        itemStyle: { color: color },
        lineStyle: { type: 'dashed', width: 2, opacity: 0.6 },
        symbol: 'none'
      });
    }
  });

  return {
    animation: false, // Critical for high-frequency 10Hz data
    tooltip: { trigger: 'axis' },
    legend: {
      data: legendData,
      textStyle: { color: '#D1D5DB' }
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
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
    series: series
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
        v-for="(data, name) in status.temperatures" 
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
