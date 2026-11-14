<script setup lang="ts">
// Running page: the panels and their places come from the page layout
// setting (Settings -> Page layout -> Running).
import PageLayout from "../layout/PageLayout.vue";
import { runningLayout } from "../settings/definitions/layout";

defineOptions({ name: 'RunningView' })
</script>

<template>
  <div class="h-full overflow-y-auto pr-2">
    <PageLayout :setting="runningLayout" />
  </div>
</template>
