<script setup lang="ts">
// Full-screen system-update overlay, mounted once in App.vue so it
// survives navigation. Driven by ``stores/systemUpdate``: it stays
// until the update script reports "done" (page reloads into the new
// build) or "failed" (reason + log tail, Close button).
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useSystemUpdateStore } from '../stores/systemUpdate'
import { BaseButton } from '../ui/index.ts'

const store = useSystemUpdateStore()
const { mode, status, unreachableSince } = storeToRefs(store)

// The steps scripts/update.sh reports, in order.
const STEPS = [
  { phase: 'checks', label: 'Checks' },
  { phase: 'pull', label: 'Download update' },
  { phase: 'dependencies', label: 'Install dependencies' },
  { phase: 'stopping services', label: 'Stop services' },
  { phase: 'rebuilding UI', label: 'Rebuild interface' },
  { phase: 'waiting for services', label: 'Restart services' },
]

const currentIndex = computed(() =>
  STEPS.findIndex((step) => step.phase === status.value?.phase),
)

function stepState(index: number): 'done' | 'current' | 'pending' {
  if (currentIndex.value < 0) return 'pending'
  if (index < currentIndex.value) return 'done'
  return index === currentIndex.value ? 'current' : 'pending'
}

const failedStep = computed(
  () => STEPS.find((step) => step.phase === status.value?.phase)?.label ?? status.value?.phase ?? '',
)
</script>

<template>
  <Teleport to="body">
    <div
      v-if="mode !== 'idle'"
      class="fixed inset-0 z-[60] flex items-center justify-center bg-gray-900/90 p-4 backdrop-blur-sm"
      data-test="update-overlay"
    >
      <div class="flex w-full max-w-md flex-col items-center rounded-xl border border-gray-700 bg-gray-800 p-8 text-center">
        <!-- running -->
        <template v-if="mode === 'running'">
          <div class="mb-6 h-16 w-16 animate-spin rounded-full border-4 border-yellow-500 border-t-transparent"></div>
          <h2 class="mb-2 text-2xl font-bold tracking-wide text-white">UPDATING SYSTEM</h2>
          <p class="mb-5 text-sm text-gray-400">
            The page reloads by itself once the system is ready again.
          </p>
          <ol class="w-full space-y-1.5 text-left text-sm" data-test="update-steps">
            <li
              v-for="(step, index) in STEPS"
              :key="step.phase"
              class="flex items-center gap-2"
              :class="{
                'text-green-400': stepState(index) === 'done',
                'font-semibold text-yellow-300': stepState(index) === 'current',
                'text-gray-500': stepState(index) === 'pending',
              }"
            >
              <span class="w-4 text-center">{{ stepState(index) === 'done' ? '✓' : stepState(index) === 'current' ? '▸' : '·' }}</span>
              {{ step.label }}
            </li>
          </ol>
          <p v-if="unreachableSince !== null" class="mt-4 text-xs text-gray-500" data-test="update-waiting">
            System is restarting — waiting for it to come back…
          </p>
        </template>

        <!-- failed / unreachable -->
        <template v-else>
          <div class="mb-4 text-5xl">❌</div>
          <h2 class="mb-2 text-2xl font-bold tracking-wide text-red-300">UPDATE FAILED</h2>
          <p v-if="mode === 'failed'" class="mb-4 text-sm text-gray-300" data-test="update-failure">
            <template v-if="failedStep">Failed during <b>{{ failedStep }}</b>. </template>{{ status?.message }}
          </p>
          <p v-else class="mb-4 text-sm text-gray-300" data-test="update-unreachable">
            The system has not come back for 10 minutes. Check <code>update.log</code> on the machine.
          </p>
          <pre
            v-if="status?.logTail"
            class="mb-4 max-h-56 w-full overflow-auto whitespace-pre-wrap break-all rounded bg-gray-950 p-3 text-left font-mono text-[11px] text-gray-400"
            data-test="update-log-tail"
          >{{ status.logTail }}</pre>
          <BaseButton variant="secondary" data-test="update-dismiss" @click="store.dismiss()">Close</BaseButton>
        </template>
      </div>
    </div>
  </Teleport>
</template>
