<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useServoThreadStore } from '../stores/servoThread'
import BaseCard from '../ui/BaseCard.vue'

// The raw telemetry payload lives in ``useServoThreadStore`` after
// the servo/base-thread split — ``stores/machine.ts`` no longer
// owns ``status`` as state, it composes it via a ``computed`` so
// ``store.$state`` holds almost nothing of its own. Reading the wrong
// store here was the reason the panel showed nothing from the live
// telemetry.
const servo = useServoThreadStore()
const throttledState = ref({})
let intervalId: ReturnType<typeof setInterval> | null = null

// Pretty JSON, but an array of plain values (numbers, strings, ...) on one
// line: "homed": [0, 0, 0] instead of one line per entry.
function formatState(value: unknown): string {
  // An array holding no object / array: join its lines (JSON strings never
  // contain a raw newline, so this only removes the layout whitespace).
  return JSON.stringify(value, null, 2).replace(
    /\[\n\s*([^[\]{}]*?)\n\s*\]/g,
    (_match, items: string) => `[${items.replace(/\n\s*/g, ' ')}]`,
  )
}

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
  <BaseCard title="Raw Machine State (3s Snapshot)" class="overflow-hidden">
    <div class="p-4 bg-gray-900 overflow-x-auto">
      <pre class="text-xs text-green-400 font-mono"><code>{{ formatState(throttledState) }}</code></pre>
    </div>
  </BaseCard>
</template>
