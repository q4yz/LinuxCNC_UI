<script setup lang="ts">
// Dashboard: the panels and their places come from the page layout
// setting (Settings -> Page layout -> Dashboard); ``PageLayout`` renders
// them. Machine-level panels mount inside ``<MachineGate>`` (only while
// the machine backend (:8000) is reachable); the console stays ungated —
// it also carries system-side rows and the offline explanation itself.

import PageLayout from "../layout/PageLayout.vue";
import { dashboardLayout } from "../settings/definitions/layout";
import { useDashboardScrollState } from "../composables/useDashboardScrollState";

defineOptions({ name: 'DashboardView' })

// Freeze the live 3D viewer + temperature chart while this view's
// own scroll container is moving — see useDashboardScrollState.ts.
// A plain ``scroll`` listener never blocks the scroll itself: unlike
// wheel/touchmove, ``scroll`` isn't cancelable, so this can't make
// scrolling feel less responsive, only make what's drawn during it
// cheaper.
const { markScrolling } = useDashboardScrollState()
</script>

<template>
  <div class="h-full overflow-y-auto pr-2" @scroll="markScrolling">
    <PageLayout :setting="dashboardLayout" />
  </div>
</template>
