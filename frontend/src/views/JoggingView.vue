<script setup lang="ts" >
import DroPanel from '../components/machine/DroPanel.vue'
import JogControls from '../components/machine/JogControls.vue'
import ToolPanel from '../components/tools/ToolPanel.vue'
import MacroPanel from '../components/macros/MacroPanel.vue'
import McodePanel from '../components/macros/McodePanel.vue'

import NgcCoordinateSystemViewer from "../components/NgcCoordinateSystemViewer.vue";
import MachineGate from "../components/machine/MachineGate.vue";
</script>

<template>
  <!-- Subtracts a 64px (4rem) top bar from the dynamic viewport height -->
  <div class="h-[calc(100dvh-64px)] overflow-hidden pr-2">
    <MachineGate label="Toolpath">
      <NgcCoordinateSystemViewer/>
    </MachineGate>
  </div>
</template>