<script setup lang="ts">
// Editor for ``camera.preferences``. The per-device list comes from the
// machine backend's camera module, so it sits behind MachineGate; the
// preferences themselves are saved to the system service.
import CameraSettings from "../../components/camera/CameraSettings.vue";
import MachineGate from "../../components/machine/MachineGate.vue";
import type { CameraPreferencesSetting } from "../types/CameraPreferencesSetting";

defineProps<{ setting: CameraPreferencesSetting }>();
</script>

<template>
  <div class="w-full">
    <MachineGate label="Camera devices">
      <CameraSettings />
    </MachineGate>
  </div>
</template>
