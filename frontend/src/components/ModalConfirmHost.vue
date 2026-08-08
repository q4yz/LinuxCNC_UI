<script setup>
import { storeToRefs } from "pinia";

import ModalConfirm from "./ModalConfirm.vue";
import { useConfirmStore } from "../core/confirm.js";

const store = useConfirmStore();
const { active } = storeToRefs(store);
</script>

<template>
  <ModalConfirm
    v-if="active"
    v-bind="active"
    @confirm="store.settle(true)"
    @reject="store.settle(false)"
  />
</template>
