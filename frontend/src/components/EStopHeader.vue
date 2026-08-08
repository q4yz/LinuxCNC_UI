<script setup>
// Global Emergency Stop header.
//
// Lives at the very top of the application shell, above the
// sidebar and the route content, so the operator can engage the
// E-Stop with a single click no matter which view they are on or
// how deep they have scrolled.  Issue #103: safety must never be
// hidden by scrolling or overlapping elements.
//
// The button delegates to the machine store's ``toggleEstop``
// action, which calls
// ``POST /api/v1/modules/machine/state`` with
// ``{state: "estop"}`` or ``{state: "estop_reset"}`` depending on
// the current machine state.  When the machine module is not
// mounted the compatibility adapter provides a no-op fallback so
// the shell still renders.

import { storeToRefs } from 'pinia'
import { useMachineStore } from '../stores/machine-compat.js'

// ``storeToRefs`` preserves reactivity when destructuring the
// ``isEstop`` flag — see ``.agent/context/LESSONS_LEARNED.md`` §
// 2.3 for the destructuring tripwire.
const store = useMachineStore()
const { isEstop } = storeToRefs(store)

// ``toggleEstop`` is the canonical action.  The store handles the
// API dispatch, surfaces a console message on success/failure,
// and the next telemetry tick flips ``isEstop`` so the header
// re-renders without a manual refresh.
async function pressEStop() {
  await store.toggleEstop()
}
</script>

<template>
  <!--
    ``sticky top-0`` keeps the header visible while the operator
    scrolls within the active view; ``z-[100]`` lifts it above the
    sidebar (``z-10``) and every modal overlay in the app (the
    full-screen editor, update manager, and panel dialogs all
    use ``z-50``).  Tailwind v4 arbitrary-value syntax.  The
    full-width background guarantees the button is reachable on
    any breakpoint, including the narrow mobile / tablet widths
    the operator might use on the shop floor.
  -->
  <header
    class="sticky top-0 z-[100] w-full bg-gray-900 border-b-2 border-red-700 shadow-lg shrink-0"
    data-testid="estop-header"
  >
    <div class="flex items-center justify-between px-4 py-2 lg:px-8 gap-4">
      <div class="flex items-center space-x-3 min-w-0">
        <span class="text-xs sm:text-sm font-semibold uppercase tracking-widest text-red-300 whitespace-nowrap">
          Emergency Stop
        </span>
        <span
          v-if="isEstop"
          class="text-xs font-mono px-2 py-0.5 rounded bg-red-700 text-white whitespace-nowrap"
          data-testid="estop-state-active"
        >
          ACTIVE
        </span>
        <span
          v-else
          class="text-xs font-mono px-2 py-0.5 rounded bg-gray-700 text-gray-300 whitespace-nowrap"
          data-testid="estop-state-clear"
        >
          Clear
        </span>
      </div>

      <!--
        Standard E-Stop iconography: large, red, prominent, with
        a hard "STOP" label so a panicked operator does not have
        to read any copy before pressing it.  ``aria-pressed``
        reflects the current state for assistive tech; ``title``
        and ``aria-label`` carry the human-readable name.
      -->
      <button
        type="button"
        class="shrink-0 flex items-center justify-center w-20 h-20 sm:w-24 sm:h-24
               bg-red-600 hover:bg-red-500 active:bg-red-700
               text-white font-extrabold uppercase tracking-widest
               rounded-full shadow-2xl border-4 border-red-800
               transition-colors focus:outline-none focus:ring-4 focus:ring-red-400"
        :aria-pressed="isEstop"
        aria-label="Emergency Stop"
        title="Emergency Stop"
        data-testid="estop-button"
        @click="pressEStop"
      >
        STOP
      </button>
    </div>
  </header>
</template>
