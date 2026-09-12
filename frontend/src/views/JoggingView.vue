<script setup lang="ts" >
import DroPanel from '../components/machine/DroPanel.vue'
import JogControls from '../components/machine/JogControls.vue'
import ToolPanel from '../components/tools/ToolPanel.vue'
import MacroPanel from '../components/macros/MacroPanel.vue'
import McodePanel from '../components/macros/McodePanel.vue'

defineOptions({ name: 'JoggingView' })
</script>

<template>
  <!-- Subtracts a 64px (4rem) top bar from the dynamic viewport height.
       The actual 3D viewer is a single instance shared with
       DashboardView, owned by App.vue, and moved here via Teleport
       while this view is active (see App.vue) — this div is just the
       slot it's teleported into. -->
  <div id="toolpath-slot-jogging" class="h-[calc(100dvh-64px)] overflow-hidden pr-2"></div>
</template>