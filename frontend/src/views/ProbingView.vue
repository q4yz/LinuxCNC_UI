<script setup lang="ts">
import ProbingPanel from "../components/probing/ProbingPanel.vue";
import MachineGate from "../components/machine/MachineGate.vue";
import { useRouter } from "vue-router";
import { BaseButton } from "../ui";

const router = useRouter();

function exitProbing() {
  router.push({ name: "dashboard" });
}
</script>

<template>
  <header class="flex items-baseline justify-between">
    <h1 class="text-2xl font-bold">Probing</h1>
    <BaseButton variant="secondary" @click="exitProbing" data-testid="probe-exit">
      Exit Probing
    </BaseButton>
  </header>

  <div class="grid grid-cols-1 gap-6 pb-8">
    <section class="space-y-6">
      <MachineGate label="Probing">
        <ProbingPanel />
      </MachineGate>
    </section>
  </div>
</template>

<style scoped>
</style>
