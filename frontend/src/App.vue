<script setup lang="ts">
// App shell. Vue Router owns the active view; the sidebar uses
// ``router.push`` for navigation and ``useRoute().name`` for
// highlighting the active entry.
//
// Machine traffic gating: the machine backend (:8000) can be down
// while the system backend (:8001) keeps running (split-backend
// deployment). The ``useMachineOnline`` heartbeat probes
// ``/api/v1/health`` and this shell starts/stops ALL machine-side
// traffic on its verdict:
//
//   * offline → stop the 1 Hz snapshot poll and close the telemetry
//     WebSocket immediately (teardown is never debounced — every
//     second of extra traffic against a dead port is 502 spam).
//   * online  → wait CONNECT_SETTLE_MS before (re)connecting so the
//     freshly booted backend has fully bound its routes; probing
//     health can succeed a fraction of a second before the WS
//     endpoint accepts connections, and an instant ``connect()``
//     would kick off the reconnect backoff loop for nothing.

import { onMounted, onUnmounted, watch } from 'vue'

import { useBaseThreadStore } from './stores/baseThread'
import { servoThreadService } from './facades/servoThreadFacade'
import { useMachineOnline } from './composables/useMachineOnline'
import AppSidebar from './components/AppSidebar.vue'
import ModalConfirmHost from './components/ModalConfirmHost.vue'
import ToastContainer from './components/ToastContainer.vue'
import EStopHeader from './components/EStopHeader.vue'

const baseThread = useBaseThreadStore()
const { isMachineOnline, startHeartbeat, stopHeartbeat } = useMachineOnline()

// Grace period between "health probe says online" and "hammer the
// backend with the WS + 1 Hz poll". 750 ms sits inside the
// 500–1000 ms window: enough for uvicorn to finish binding every
// route after the health route answers, short enough that the
// operator never notices.
const CONNECT_SETTLE_MS = 750

let connectTimer: number | null = null

function startMachineTraffic(): void {
  // Idempotent per design (poll handle guard, singleton socket
  // service) — safe to call repeatedly as online flaps.
  baseThread.start()
  servoThreadService.connect()
}

function stopMachineTraffic(): void {
  if (connectTimer !== null) {
    window.clearTimeout(connectTimer)
    connectTimer = null
  }
  baseThread.stop()
  servoThreadService.disconnect()
}

watch(isMachineOnline, (next) => {
  if (next === false) {
    stopMachineTraffic()
    return
  }
  if (next === true) {
    if (connectTimer !== null) window.clearTimeout(connectTimer)
    connectTimer = window.setTimeout(() => {
      connectTimer = null
      startMachineTraffic()
    }, CONNECT_SETTLE_MS)
  }
})

onMounted(() => {
  startHeartbeat()
})

onUnmounted(() => {
  stopHeartbeat()
  stopMachineTraffic()
})
</script>

<template>
  <div class="flex flex-col h-screen overflow-hidden bg-gray-900 text-white font-sans">

    <!-- Global Emergency Stop header. -->
    <EStopHeader />

    <!-- Sidebar + main content row. -->
    <div class="flex flex-1 overflow-hidden">

      <!-- Sidebar Navigation -->

      <div class="w-16 shrink-0"></div>
      <AppSidebar class="absolute top-0 left-0 h-full z-40  transition-all" />

      <!-- Main Content Area -->
      <main class="flex-1 overflow-y-auto p-4 lg:p-8">
        <router-view />
      </main>

    </div>

    <!-- Global Overlays -->
    <ModalConfirmHost />
    <ToastContainer />

  </div>
</template>
