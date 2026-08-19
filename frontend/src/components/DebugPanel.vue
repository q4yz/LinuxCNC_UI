<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useServoThreadStore } from '../stores/servoThread'

// The raw telemetry payload lives in ``useServoThreadStore`` after
// the servo/base-thread split — ``stores/machine.ts`` no longer
// owns ``status`` as state, it composes it via a ``computed`` so
// ``store.$state`` only contains the module-private settings
// (``defaultJogVelocity`` / ``keepaliveIntervalMs``). Reading the
// wrong store here was the reason the panel showed only those two
// fields and nothing from the live telemetry.
const servo = useServoThreadStore()
const throttledState = ref({})
let intervalId = null

function snapshot() {
  const s = servo.status
  throttledState.value = {
    connectionStatus: servo.connectionStatus,
    status: {
      task_state: s.taskState,
      estop: s.estop,
      task_mode: s.taskMode,
      position: s.position,
      actual_position: s.actualPosition,
      relative_position: s.relativePosition,
      state: s.state,
      file: s.file,
      homed: s.homed,
      interp_state: s.interpState,
      g5x_index: s.g5xIndex,
      g5x_offset: s.g5xOffset,
      g92_offset: s.g92Offset,
      current_line: s.currentLine,
      total_lines: s.totalLines,
      errors: s.errors,
    },
  }
}

onMounted(() => {
  // Take an initial snapshot immediately
  snapshot()

  // Update snapshot every 3000ms
  intervalId = setInterval(snapshot, 3000)
})

onUnmounted(() => {
  if (intervalId) {
    clearInterval(intervalId)
  }
})
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 shadow-xl overflow-hidden flex flex-col h-full">
    <!-- Header -->
    <div class="bg-gray-700/50 px-4 py-2 border-b border-gray-600 flex justify-between items-center">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">Raw Machine State (3s Snapshot)</h2>
    </div>
    
    <!-- Code Area -->
    <div class="flex-1 p-4 bg-gray-900 overflow-y-auto">
      <pre><code class="text-xs text-green-400 font-mono">{{ JSON.stringify(throttledState, null, 2) }}</code></pre>
    </div>
  </div>
</template>
