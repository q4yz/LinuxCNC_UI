<script setup lang="ts">
import { storeToRefs } from "pinia";
import useMachineStore from "../../stores/machine";
import BaseCard from "../../ui/BaseCard.vue";
import { BaseButton } from "../../ui";

const store = useMachineStore()
const { isEstop, isMachineOn, machineStateText } = storeToRefs(store)

</script>

<template>

  <BaseCard
      :class="isEstop ? 'bg-red-900 border-red-500' : ''"
  >
    <div class="flex items-center justify-between p-2">

      <div class="flex items-center space-x-4">
        <div class="text-2xl font-bold uppercase tracking-widest text-white">
          STATE: {{ machineStateText }}
        </div>
      </div>
      <div class="flex space-x-3">
        <BaseButton
            @click="store.toggleEstop()"
            :variant="isEstop ? 'danger' : 'secondary'"
            size="lg"
        >
          E-STOP
        </BaseButton>

        <BaseButton
            @click="store.togglePower()"
            :variant="isMachineOn ? 'success' : 'secondary'"
            :disabled="isEstop && !isMachineOn"
            size="lg"
        >
          POWER
        </BaseButton>
      </div>

    </div>
  </BaseCard>
</template>

<style scoped>
</style>