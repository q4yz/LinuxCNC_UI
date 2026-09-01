<script setup lang="ts">
// Config page shell.
//
// Hosts the ``HttpsBanner`` that nudges operators off plain HTTP onto
// the nginx-served HTTPS origin (port 443), plus a small install guide
// that walks through trusting the mkcert root CA on a client device.
// The banner self-hides on HTTPS so the page is informative but quiet
// when the operator is already on the secure origin.

import HttpsBanner from '../components/HttpsBanner.vue'
import ActivePanel from "../components/machineconfig/ActivePanel.vue";
import DebugPanel from "../components/DebugPanel.vue";
import MacroManagerPanel from "../components/macros/MacroManagerPanel.vue";
import McodeManagerPanel from "../components/macros/McodeManagerPanel.vue";
import UpdateManager from "../components/UpdateManager.vue";
</script>

<template>
  <!-- Replaced space-y-6 with flex and gap -->
  <div class="flex flex-col gap-6" data-test="config-view">

    <header class="flex items-baseline justify-between mb-2">
      <h1 class="text-2xl font-bold">Configuration</h1>
    </header>

    <!-- Added items-start to force top alignment -->
    <div class="grid grid-cols-1 gap-6 pb-8 xl:grid-cols-12 items-start">

      <!-- Replaced space-y-6 with flex flex-col gap-6 -->
      <section class="flex flex-col gap-6 xl:col-span-4">
        <HttpsBanner />
        <MacroManagerPanel />
      </section>

      <!-- Replaced space-y-6 with flex flex-col gap-6 -->
      <section class="flex flex-col gap-6 xl:col-span-8">
        <UpdateManager />
        <ActivePanel />
        <McodeManagerPanel />
      </section>

    </div>
  </div>
</template>

<style scoped>
</style>
