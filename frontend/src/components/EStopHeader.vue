<script setup>
// Global Emergency Stop header. Pinned to the top-right of the
// shell so the operator can press it regardless of the active
// route. ``App.vue`` mounts it once outside the scrolling ``<main>``.
//
// The header now carries a small machine-state readout directly
// under the button. The state string comes from the canonical
// State Facade (``stores/stateFacade.js::systemState``) which
// always tracks the current LinuxCNC facet — high-resolution
// vocabulary (Estop / PowerOff / Idle / Running / Paused /
// Loaded / Offline / Updating / Failure). Every state change is
// mirrored to the console store so the operator has a written
// record of transitions without needing to watch the badge.

import { computed, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useMachineStore } from '../stores/machineStoreShim.js'
// Direct facade import for the high-resolution ``systemState``
// getter. The machine store (``modules/machine/store.js``) only
// exposes the coarser ``machineStateText`` (ESTOP/OFF/ON/READY);
// the facade is the canonical source for the 8-state vocabulary
// per ``.agent/STATE.md`` § 6.
import { useMachineStore as useFacadeStore } from '../stores/stateFacade.js'

const store = useMachineStore()
const facade = useFacadeStore()
// ``storeToRefs`` preserves reactivity for both the legacy compat
// (``isEstop``) and the facade (``systemState``) — plain ES
// destructuring would silently lose Pinia reactivity (see
// ``.agent/context/LESSONS_LEARNED.md`` § 2.3).
const { isEstop } = storeToRefs(store)
const { systemState } = storeToRefs(facade)

async function pressEStop() {
  await store.toggleEstop()
}

// Color bucket per systemState. Lifted out of the template so a
// future state addition only needs to touch this map.
const STATE_COLOR = {
  Estop: ['text-red-400', 'border-red-700'],
  PowerOff: ['text-amber-300', 'border-amber-700'],
  Offline: ['text-slate-400', 'border-slate-700'],
  Updating: ['text-slate-300', 'border-slate-600'],
  Failure: ['text-red-400', 'border-red-700'],
  Running: ['text-emerald-300', 'border-emerald-700'],
  Paused: ['text-yellow-300', 'border-yellow-700'],
  Loaded: ['text-indigo-300', 'border-indigo-700'],
  Idle: ['text-emerald-200', 'border-emerald-700'],
}
const stateBadgeClass = computed(() => {
  const colors = STATE_COLOR[systemState.value] || ['text-gray-300', 'border-gray-700']
  return `${colors[0]} border ${colors[1]}`
})

// Log every transition (including the first) so the operator gets
// a written record. ``Estop`` and ``PowerOff`` are escalated to
// warning rows; everything else is ``info``. The console store is
// imported lazily inside the watcher — module-init order between
// the console store and the facade would otherwise risk a Pinia
// "no active pinia" error per ``LESSONS_LEARNED.md`` § 2.4. The
// no-op ``next === prev`` guard skips duplicate frames that
// re-deliver the same value (the WebSocket occasionally replays
// the same state when only axis positions change).
watch(systemState, async (next, prev) => {
  if (next === prev) return
  const { useConsoleStore } = await import('../stores/console.js')
  const consoleStore = useConsoleStore()
  const text = prev === undefined
    ? `Machine state: ${next}`
    : `Machine state: ${prev} → ${next}`
  if (next === 'Estop' || next === 'PowerOff') {
    consoleStore.warning(text)
  } else {
    consoleStore.info(text)
  }
})
</script>

<template>
  <!--
    The gray container box anchors the button to the top-right corner.
    rounded-bl-xl gives it a control-panel look rather than just floating.
  -->
  <div class="fixed top-0 right-0 z-[100] bg-gray-800 p-3 sm:p-4 shadow-xl border-b border-l border-gray-700 rounded-bl-xl">

    <!--
      The button is now square (w-20 h-20) with slightly rounded corners (rounded-md).
      We use dynamic classes to switch between the "Normal" and "Pressed" states.
    -->
    <button
      type="button"
      :class="[
        'flex items-center justify-center w-20 h-20 sm:w-24 sm:h-12',
        'text-white font-extrabold uppercase tracking-widest text-xl',
        'border-4 rounded-md transition-all focus:outline-none',
        isEstop
          ? 'bg-red-900 border-black shadow-inner scale-95 translate-y-1' // Darker, pushed-in look
          : 'bg-red-600 hover:bg-red-500 active:bg-red-800 border-red-900 shadow-lg' // Bright, popped-out look
      ]"
      :aria-pressed="isEstop"
      aria-label="Emergency Stop"
      title="Emergency Stop"
      data-testid="estop-button"
      @click="pressEStop"
    >
      STOP
    </button>

    <!-- Machine-state readout. The ``role="status"`` + ``aria-live``
         wires the badge to the screen-reader announcement channel
         (assertive when Estop so a sighted-reader-equivalent announce
         fires; polite otherwise). -->
    <div
      :class="['mt-2 rounded border px-2 py-1 text-center font-mono text-[10px] uppercase tracking-widest', stateBadgeClass]"
      role="status"
      aria-live="polite"
      data-testid="estop-machine-state"
    >
      {{ systemState }}
    </div>
  </div>
</template>
