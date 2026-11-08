<script setup lang="ts">
// LED card: a colour picker per segment of every [neopixel] chain
// (`.agent/component/neopixel.md`), and "off" per chain. Polled, so a
// SET_LED / M150 from G-code shows up; a colour is sent when picked.
import { onBeforeUnmount, onMounted, ref } from "vue";
import { colorToHex, hexToColor, ledsFacade, type Led } from "../../facades/ledsFacade";
import BaseCard from "../../ui/BaseCard.vue";
import { describeError } from "../../core/error-format";
import { useConsoleStore } from "../../stores/console";

const POLL_MS = 1000;

const consoleStore = useConsoleStore();
const leds = ref<Led[]>([]);
let timer: ReturnType<typeof setInterval> | null = null;

async function poll() {
  try {
    leds.value = await ledsFacade.list();
  } catch {
    // MachineGate shows when the machine backend is down
  }
}

async function pick(id: string, first: number, event: Event) {
  const hex = (event.target as HTMLInputElement).value;
  try {
    leds.value = await ledsFacade.set(id, hexToColor(hex), first);
  } catch (err) {
    consoleStore.error(`LED ${id}: ${describeError(err)}`);
  }
}

async function off(id: string) {
  try {
    leds.value = await ledsFacade.set(id, { red: 0, green: 0, blue: 0 });
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

onMounted(() => {
  void poll();
  timer = setInterval(poll, POLL_MS);
});
onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
});
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
              :value="colorToHex(seg)"
              @change="pick(led.id, seg.first, $event)"
            />
            <span v-if="led.segments.length > 1">{{ range(seg.first, seg.count) }}</span>
          </label>
        </div>
      </div>
    </div>
  </BaseCard>
</template>
