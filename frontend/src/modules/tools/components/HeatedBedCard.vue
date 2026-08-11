<script setup>
// Heated bed card — heat-only tool. Wraps the shared
// ``HeaterControls`` block so the operator gets the same Set Temp /
// Off affordance as every other heating tool. The bed also stays
// on the temperature chart (the temperature module reads
// ``temperature_sensors[]`` + ``tools[]`` independently of this
// panel).

import HeaterControls from "./HeaterControls.vue";

defineProps({
  tool: { type: Object, required: true },
});
</script>

<template>
  <HeaterControls :tool="tool" />
</template>