<script setup>
import { storeToRefs } from "pinia";

import ModalConfirm from "./ModalConfirm.vue";
import { useConfirmStore } from "../core/confirm";

const store = useConfirmStore();
const { active } = storeToRefs(store);
</script>

<template>
  <Teleport to="body">
    <ModalConfirm
      v-if="active"
      v-bind="active"
      @confirm="store.settle(true)"
      @reject="store.settle(false)"
    />
  </Teleport>
</template>
