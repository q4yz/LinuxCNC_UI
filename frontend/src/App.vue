<script setup lang="ts">
// App shell. Vue Router owns the active view; the sidebar uses
// ``router.push`` for navigation and ``useRoute().name`` for
// highlighting the current entry.

import { useBaseThreadStore } from './stores/baseThread'
import { servoThreadService } from './facades/servoThreadFacade'
import AppSidebar from './components/AppSidebar.vue'
import ModalConfirmHost from './components/ModalConfirmHost.vue'
import ToastContainer from './components/ToastContainer.vue'
import EStopHeader from './components/EStopHeader.vue'

// The base-thread store is the dashboard's "slow channel" — one
// 1 Hz REST round-trip that bundles every slow stream (program
// progress, temperature sensors, tool list) into one payload. We
// boot it at app mount rather than from any specific panel so a
// view mounted later (e.g. the dashboard's ActivePrintWidget) gets
// populated data on its first frame instead of waiting a second
// for the first poll to land. The poll is cheap enough (one HTTP
// request per second) to keep running for the entire session.
useBaseThreadStore().start()

// Open the 10 Hz ``/ws/telemetry`` WebSocket at app mount. The
// state facade's ``systemState`` getter short-circuits to
// ``Offline`` until this connects — the E-Stop badge and every
// servo-driven read (jog, machine state, machineStateText) sit
// on that flag, so without this call the shell renders
// permanently offline and the E-Stop toggle is stuck because its
// engage-vs-disarm decision reads from the never-populated
// ``status.value.isEstop``. The service guards against duplicate
// sockets, so it is safe to call once per mount.
servoThreadService.connect()
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