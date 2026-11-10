<script setup lang="ts">
// LED card: a colour picker per segment of every [neopixel] chain
// (`.agent/component/neopixel.md`), and "off" per chain. The colours
// come with the base-thread snapshot (``stores/baseThread`` ``leds``),
// so a SET_LED / M150 from G-code shows up; a colour is sent when the
// picker closes.
//
// While a picker is open its colour is kept locally: each snapshot used
// to rewrite the input's value, so the picker snapped back to the old
// colour and, on closing, sent that old colour again.
import { ref } from "vue";
import { storeToRefs } from "pinia";
import { colorToHex, hexToColor, ledsFacade } from "../../facades/ledsFacade";
import BaseCard from "../../ui/BaseCard.vue";
import { describeError } from "../../core/error-format";
import { useConsoleStore } from "../../stores/console";
import useBaseThreadStore from "../../stores/baseThread";

const consoleStore = useConsoleStore();
const baseThread = useBaseThreadStore();
const { leds } = storeToRefs(baseThread);

/** ``"<led>:<first>"`` -> the colour being picked there. */
const editing = ref<Record<string, string>>({});
const key = (id: string, first: number) => `${id}:${first}`;

function shown(id: string, first: number, color: { red: number; green: number; blue: number }): string {
  return editing.value[key(id, first)] ?? colorToHex(color);
}

function onInput(id: string, first: number, event: Event) {
  editing.value = { ...editing.value, [key(id, first)]: (event.target as HTMLInputElement).value };
}

async function pick(id: string, first: number, event: Event) {
  const hex = (event.target as HTMLInputElement).value;
  try {
    baseThread.applyLeds(await ledsFacade.set(id, hexToColor(hex), first));
  } catch (err) {
    consoleStore.error(`LED ${id}: ${describeError(err)}`);
  } finally {
    const { [key(id, first)]: _done, ...rest } = editing.value;
    editing.value = rest;
  }
}

async function off(id: string) {
  try {
    baseThread.applyLeds(await ledsFacade.set(id, { red: 0, green: 0, blue: 0 }));
  } catch (err) {
    consoleStore.error(`LED ${id}: ${describeError(err)}`);
  }
}

function label(id: string): string {
  return id.replace(/_/g, " ");
}

function range(first: number, count: number): string {
  return count > 1 ? `LEDs ${first}–${first + count - 1}` : `LED ${first}`;
}
</script>

<template>
  <BaseCard v-if="leds.length" data-testid="led-panel">
    <div class="border-b border-gray-600 bg-gray-700/50 px-4 py-3">
      <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-300">LEDs</h2>
    </div>
    <div class="space-y-4 p-4">
      <div v-for="led in leds" :key="led.id" class="space-y-2" :data-testid="`led-${led.id}`">
        <div class="flex items-center justify-between text-sm">
          <span class="capitalize text-gray-200">{{ label(led.id) }}</span>
          <button
            type="button"
            class="rounded bg-gray-600 px-2 py-0.5 text-xs text-gray-200 hover:bg-gray-500"
            @click="off(led.id)"
          >
            Off
          </button>
        </div>
        <div class="flex flex-wrap gap-3">
          <label
            v-for="seg in led.segments" :key="seg.first"
            class="flex items-center gap-2 text-xs text-gray-400"
          >
            <input
              type="color" class="h-8 w-10 cursor-pointer rounded border border-gray-600 bg-transparent"
              :value="shown(led.id, seg.first, seg)"
              @input="onInput(led.id, seg.first, $event)"
              @change="pick(led.id, seg.first, $event)"
            />
            <span v-if="led.segments.length > 1">{{ range(seg.first, seg.count) }}</span>
          </label>
        </div>
      </div>
    </div>
  </BaseCard>
</template>
