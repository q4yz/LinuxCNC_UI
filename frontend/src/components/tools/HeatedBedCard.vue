<script setup lang="ts">
// Heated bed (or any heat-only tool): the shared heater controls on
// the tool's own ``HeaterState``.

import type { HeaterState } from "../../entities/tools/Heater";
import HeaterControls from "./HeaterControls.vue";

defineProps<{ tool: HeaterState }>();
</script>

<template>
  <HeaterControls :tool-id="tool.id" :heater="tool" />
</template>
