<script setup lang="ts">
// I/O card: a slider per [fan] (0 ... 100 %) and per PWM [output_pin]
// (0 ... its scale), a toggle per switched [output_pin], a lamp per
// [input_pin]. The state comes with the base-thread snapshot
// (``stores/baseThread`` ``io``), so inputs and values set elsewhere
// (G-code, another client) show up; a slider is only sent on release.
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { ioFacade } from "../../facades/ioFacade";
import useBaseThreadStore from "../../stores/baseThread";
import BaseCard from "../../ui/BaseCard.vue";
import { describeError } from "../../core/error-format";
import { useConsoleStore } from "../../stores/console";

const consoleStore = useConsoleStore();
const baseThread = useBaseThreadStore();
const { io } = storeToRefs(baseThread);
// the slider being dragged keeps its local value until it is released
const dragging = ref<Record<string, number>>({});

const isEmpty = computed(
  () => !io.value.fans?.length && !io.value.outputs?.length && !io.value.inputs?.length,
);

function shown(id: string, value: number): number {
  return dragging.value[id] ?? value;
}

function onDrag(id: string, event: Event) {
  dragging.value = { ...dragging.value, [id]: Number((event.target as HTMLInputElement).value) };
}

async function send(id: string, value: number) {
  try {
    baseThread.applyIo(await ioFacade.set(id, value));
  } catch (err) {
    consoleStore.error(`I/O: setting ${id} failed: ${describeError(err)}`);
  } finally {
    const { [id]: _released, ...rest } = dragging.value;
    dragging.value = rest;
  }
}

function label(id: string): string {
  return id.replace(/_/g, " ");
}
</script>

<template>
  <BaseCard data-testid="io-panel">
    <div class="border-b border-gray-600 bg-gray-700/50 px-4 py-3">
      <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-300">I/O</h2>
    </div>
    <div class="space-y-4 p-4">
      <p v-if="isEmpty" class="text-center text-sm text-gray-500">
        No fans, output pins or input pins in this machine's profile.
      </p>

      <div v-for="fan in io.fans" :key="fan.id" class="space-y-1" :data-testid="`io-fan-${fan.id}`">
        <div class="flex justify-between text-sm">
          <span class="capitalize text-gray-200">{{ label(fan.id) }}</span>
          <span class="font-mono text-gray-400">{{ Math.round(shown(fan.id, fan.value)) }} %</span>
        </div>
        <input
          type="range" min="0" max="100" step="1" class="w-full accent-blue-500"
          :value="shown(fan.id, fan.value)"
          @input="onDrag(fan.id, $event)"
          @change="send(fan.id, Number(($event.target as HTMLInputElement).value))"
        />
      </div>

      <div v-for="out in io.outputs" :key="out.id" :data-testid="`io-output-${out.id}`">
        <div v-if="out.pwm" class="space-y-1">
          <div class="flex justify-between text-sm">
            <span class="capitalize text-gray-200">{{ label(out.id) }}</span>
            <span class="font-mono text-gray-400">{{ +shown(out.id, out.value).toFixed(2) }} / {{ out.scale ?? 1 }}</span>
          </div>
          <input
            type="range" min="0" :max="out.scale ?? 1" :step="(out.scale ?? 1) / 100" class="w-full accent-blue-500"
            :value="shown(out.id, out.value)"
            @input="onDrag(out.id, $event)"
            @change="send(out.id, Number(($event.target as HTMLInputElement).value))"
          />
        </div>
        <label v-else class="flex cursor-pointer items-center justify-between text-sm">
          <span class="capitalize text-gray-200">{{ label(out.id) }}</span>
          <button
            type="button" role="switch" :aria-checked="out.value > 0"
            class="relative h-6 w-11 rounded-full transition-colors"
            :class="out.value > 0 ? 'bg-green-600' : 'bg-gray-600'"
            @click="send(out.id, out.value > 0 ? 0 : 1)"
          >
            <span
              class="absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all"
              :class="out.value > 0 ? 'left-5' : 'left-0.5'"
            ></span>
          </button>
        </label>
      </div>

      <div v-for="inp in io.inputs" :key="inp.id" class="flex items-center justify-between text-sm" :data-testid="`io-input-${inp.id}`">
        <span class="capitalize text-gray-200">{{ label(inp.id) }}</span>
        <span class="flex items-center gap-2 font-mono text-xs text-gray-400">
          {{ inp.value ? "on" : "off" }}
          <span class="h-3 w-3 rounded-full" :class="inp.value ? 'bg-green-400 ring-2 ring-green-400/40' : 'bg-gray-600'"></span>
        </span>
      </div>
    </div>
  </BaseCard>
</template>
