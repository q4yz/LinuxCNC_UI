<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useMachineStore } from '../stores/machine'

const store = useMachineStore()
const JOG_SPEED = 500;

const isContinuous = ref(true);
const stepSize = ref(10);
const pressedKeys = new Set(); // Track pressed keys to avoid duplicates

const startJog = (axis, dir) => {
  if (!isContinuous.value) {
    store.jog(axis, stepSize.value * Math.sign(dir));
    return;
  }
  
  // Hand off continuous logic completely to the Pinia store
  store.jogContinuous(axis, JOG_SPEED * Math.sign(dir));
}

const stopJog = (axis) => {
  if (!isContinuous.value) return; // Incremental stops automatically
  store.jogStop(axis);
}

// Global Keydown Handler
const handleKeyDown = (event) => {
  // CRITICAL SAFETY: Prevent multiple events firing while the key is held down
  if (event.repeat) return;

  // Do not trigger jogging if the user is typing in an input field
  if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;

  let axis = -1;
  let dir = 0;

  switch (event.code) {
    case 'ArrowRight': axis = 0; dir = 1; break;
    case 'ArrowLeft': axis = 0; dir = -1; break;
    case 'ArrowUp': axis = 1; dir = 1; break;
    case 'ArrowDown': axis = 1; dir = -1; break;
    case 'PageUp': axis = 2; dir = 1; break;
    case 'PageDown': axis = 2; dir = -1; break;
  }

  if (axis !== -1) {
    // Only trigger if we aren't already tracking this exact key
    if (!pressedKeys.has(event.code)) {
      pressedKeys.add(event.code);
      startJog(axis, dir);
    }
    event.preventDefault();
  }
}

// Global Keyup Handler
const handleKeyUp = (event) => {
  let axis = -1;
  switch (event.code) {
    case 'ArrowRight': 
    case 'ArrowLeft': axis = 0; break;
    case 'ArrowUp': 
    case 'ArrowDown': axis = 1; break;
    case 'PageUp': 
    case 'PageDown': axis = 2; break;
  }

  if (axis !== -1 && pressedKeys.has(event.code)) {
    pressedKeys.delete(event.code);
    stopJog(axis);
    event.preventDefault();
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown);
  window.addEventListener('keyup', handleKeyUp);
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeyDown);
  window.removeEventListener('keyup', handleKeyUp);
})
</script>

<template>
  <!-- Jog / Control Panel -->
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden mt-6">
    <div class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex justify-between items-center">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">Jog Controls</h2>
      
      <!-- Jog Mode Toggle -->
      <div class="flex items-center space-x-2">
        <div class="flex bg-gray-900 rounded overflow-hidden border border-gray-600">
          <button 
            @click="isContinuous = true" 
            class="px-3 py-1 text-xs font-semibold transition-colors"
            :class="isContinuous ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'"
          >
            Continuous
          </button>
          <button 
            @click="isContinuous = false" 
            class="px-3 py-1 text-xs font-semibold transition-colors border-l border-gray-600"
            :class="!isContinuous ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'"
          >
            Step
          </button>
        </div>
        
        <select v-if="!isContinuous" v-model="stepSize" class="bg-gray-900 border border-gray-600 text-gray-200 text-xs rounded px-2 py-1 outline-none">
          <option :value="0.1">0.1 mm</option>
          <option :value="1">1.0 mm</option>
          <option :value="10">10 mm</option>
          <option :value="50">50 mm</option>
        </select>
      </div>
    </div>
    
    <div class="p-6 grid grid-cols-3 gap-3 text-center">
      <!-- Y and Z controls -->
      <div class="col-start-2">
        <button 
          @mousedown="startJog(1, 1)" @mouseup="stopJog(1)" @mouseleave="stopJog(1)"
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors">Y+ (↑)</button>
      </div>
      <div class="col-start-3">
        <button 
          @mousedown="startJog(2, 1)" @mouseup="stopJog(2)" @mouseleave="stopJog(2)"
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors">Z+ (PgUp)</button>
      </div>
      
      <!-- X controls -->
      <div class="col-start-1">
        <button 
          @mousedown="startJog(0, -1)" @mouseup="stopJog(0)" @mouseleave="stopJog(0)"
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors">X- (←)</button>
      </div>
      <div class="col-start-2 flex items-center justify-center">
        <div class="h-4 w-4 rounded-full bg-gray-600 shadow-inner"></div>
      </div>
      <div class="col-start-3">
        <button 
          @mousedown="startJog(0, 1)" @mouseup="stopJog(0)" @mouseleave="stopJog(0)"
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors">X+ (→)</button>
      </div>
      
      <!-- Y and Z down -->
      <div class="col-start-2">
        <button 
          @mousedown="startJog(1, -1)" @mouseup="stopJog(1)" @mouseleave="stopJog(1)"
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors">Y- (↓)</button>
      </div>
      <div class="col-start-3">
        <button 
          @mousedown="startJog(2, -1)" @mouseup="stopJog(2)" @mouseleave="stopJog(2)"
          class="w-full bg-gray-700 hover:bg-gray-600 active:bg-blue-600 py-3 rounded text-lg font-bold transition-colors">Z- (PgDn)</button>
      </div>
    </div>
  </div>
</template>
