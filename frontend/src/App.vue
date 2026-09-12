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

import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { useBaseThreadStore } from './stores/baseThread'
import { servoThreadService } from './facades/servoThreadFacade'
import { useMachineOnline } from './composables/useMachineOnline'
import AppSidebar from './components/AppSidebar.vue'
import ModalConfirmHost from './components/ModalConfirmHost.vue'
import ToastContainer from './components/ToastContainer.vue'
import EStopHeader from './components/EStopHeader.vue'
import MachineGate from './components/machine/MachineGate.vue'
import NgcCoordinateSystemViewer from './components/NgcCoordinateSystemViewer.vue'
import { useDashboardScrollState } from './composables/useDashboardScrollState'

const baseThread = useBaseThreadStore()
const { isMachineOnline, startHeartbeat, stopHeartbeat } = useMachineOnline()

// ------------------------------------------------------------------- //
// Shared 3D toolpath viewer                                            //
// ------------------------------------------------------------------- //
//
// DashboardView and JoggingView both used to mount their own
// NgcCoordinateSystemViewer, so switching between the two views
// tore down one WebGL context/Three.js scene and built a new one
// from scratch on every click — expensive even on a desktop, far
// worse on a GPU-less target. A single instance lives here instead
// and is handed between the two views via Teleport (which moves the
// existing DOM node — including the live canvas/GL context — rather
// than destroying and recreating it). ``isToolpathViewActive`` tells
// the viewer to pause its render loop while parked on an unrelated
// route instead of rendering an invisible canvas.
//
// The target is set from a ``post``-flush watcher (not a plain
// computed) so it only flips *after* Vue has patched <router-view>
// for the new route — the destination slot ``<div>`` (rendered by
// the now-active/reactivated view) is guaranteed to already exist
// in the document by the time Teleport looks it up.
const route = useRoute()
const { isScrolling } = useDashboardScrollState()
// Also pause the render loop while Dashboard's own scroll container
// is moving — the viewer is a live, continuously-redrawing canvas
// competing with the scroll for the same raster thread on a
// GPU-less target. See useDashboardScrollState.ts.
const isToolpathViewActive = computed(
  () => (route.name === 'dashboard' || route.name === 'jogging') && !isScrolling.value,
)
const toolpathTeleportTarget = ref('#toolpath-parking')

watch(
  () => route.name,
  () => {
    if (route.name === 'dashboard') toolpathTeleportTarget.value = '#toolpath-slot-dashboard'
    else if (route.name === 'jogging') toolpathTeleportTarget.value = '#toolpath-slot-jogging'
    else toolpathTeleportTarget.value = '#toolpath-parking'
  },
  { immediate: true, flush: 'post' },
)

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
        <!-- The three heaviest views (WebGL viewer, ECharts, live
             camera/telemetry-bound widgets) are kept alive across
             navigation so switching between them toggles visibility
             instead of paying a full unmount+remount cost on every
             sidebar click. Every other view keeps its normal
             mount/unmount lifecycle (e.g. the file list refetching
             on each visit). -->
        <router-view v-slot="{ Component }">
          <keep-alive :include="['DashboardView', 'JoggingView', 'RunningView']">
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </main>

    </div>

    <!-- Shared 3D toolpath viewer — a single instance, handed to
         whichever of Dashboard/Jogging is active via Teleport (see
         script setup above). Parked (hidden, RAF loop paused) in
         index.html's #toolpath-parking div — which must live outside
         this component tree, see the comment there — when neither
         view is on screen. -->
    <Teleport :to="toolpathTeleportTarget">
      <MachineGate label="Toolpath">
        <NgcCoordinateSystemViewer :active="isToolpathViewActive" />
      </MachineGate>
    </Teleport>

    <!-- Global Overlays -->
    <ModalConfirmHost />
    <ToastContainer />

  </div>
</template>
