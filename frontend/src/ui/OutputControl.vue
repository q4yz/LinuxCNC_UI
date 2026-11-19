<script setup lang="ts">
// A macro button of kind "output": its icon and name, then the control the
// output takes — a toggle (switched [output_pin]), a slider (PWM pin, fan)
// or a colour picker ([neopixel] chain) — set straight away (a slider on
// release, a colour when the picker closes), like the I/O and LED cards.
// The value shown is the machine's (base-thread snapshot), so a change
// from G-code or another client shows up.
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import Icon from "./Icon.vue";
import useBaseThreadStore from "../stores/baseThread";
import { ioFacade } from "../facades/ioFacade";
import { colorToHex, hexToColor, ledsFacade } from "../facades/ledsFacade";
import { useConsoleStore } from "../stores/console";
import { describeError } from "../core/error-format";
import { findTarget, splitTarget } from "./outputTargets";
import type { MacroButtonDescriptor } from "./macroButtonTypes";

const props = defineProps<{ descriptor: MacroButtonDescriptor; iconKnown: boolean; size?: string }>();

const baseThread = useBaseThreadStore();
const { io, leds } = storeToRefs(baseThread);
const consoleStore = useConsoleStore();

const target = computed(() => findTarget(props.descriptor.macroName ?? "", io.value, leds.value));
const parts = computed(() => splitTarget(props.descriptor.macroName ?? ""));

const current = computed<number>(() => {
  const [type, id] = parts.value;
  if (type === "out") return io.value?.outputs?.find((o) => o.id === id)?.value ?? 0;
  if (type === "fan") return io.value?.fans?.find((f) => f.id === id)?.value ?? 0;
  return 0;
});
const currentColor = computed(() => {
  const led = leds.value?.find((l) => l.id === parts.value[1]);
  const segment = led?.segments?.[0];  // the chain's first segment stands for it
  return segment ? colorToHex(segment) : "#000000";
});

// a slider being dragged / a picker open keeps its local value
const dragging = ref<number | null>(null);
const picking = ref<string | null>(null);
const busy = ref(false);

async function setValue(value: number) {
  const [, id] = parts.value;
  busy.value = true;
  try {
    baseThread.applyIo(await ioFacade.set(id, value));
  } catch (err) {
    consoleStore.error(`${props.descriptor.name || id}: ${describeError(err)}`);
  } finally {
    busy.value = false;
    dragging.value = null;
  }
}

async function setColor(hex: string) {
  const [, id] = parts.value;
  try {
    baseThread.applyLeds(await ledsFacade.set(id, hexToColor(hex)));
  } catch (err) {
    consoleStore.error(`${props.descriptor.name || id}: ${describeError(err)}`);
  } finally {
    picking.value = null;
  }
}

const textSize = computed(() => (props.size === "lg" ? "text-base" : props.size === "md" ? "text-sm" : "text-xs"));
</script>

<template>
  <span
      class="inline-flex items-center gap-2 rounded-md border border-gray-600 bg-gray-700 px-2 py-1 font-semibold text-gray-100"
      :class="[textSize, target ? '' : 'opacity-50']"
      :title="target ? descriptor.name || target.label : `${descriptor.macroName}: not on this machine (now)`"
      :data-testid="`output-control-${descriptor.slot}`"
  >
    <Icon v-if="iconKnown" :name="descriptor.icon ?? ''" size="h-4 w-4" />
    <span v-else-if="descriptor.icon">{{ descriptor.icon }}</span>
    <span v-if="descriptor.name" class="whitespace-nowrap">{{ descriptor.name }}</span>

    <template v-if="target?.control === 'toggle'">
      <button
          type="button" role="switch" :aria-checked="current > 0" :disabled="busy"
          :aria-label="`${descriptor.name || target.label} ${current > 0 ? 'off' : 'on'}`"
          class="relative h-5 w-9 shrink-0 rounded-full transition-colors"
          :class="current > 0 ? 'bg-green-600' : 'bg-gray-500'"
          :data-testid="`output-toggle-${descriptor.slot}`"
          @click="setValue(current > 0 ? 0 : 1)"
      >
        <span class="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all" :class="current > 0 ? 'left-4' : 'left-0.5'" />
      </button>
    </template>
    <template v-else-if="target?.control === 'slider'">
      <input
          type="range" min="0" :max="target.max" :step="target.max / 100"
          class="accent-blue-500"
          :class="size === 'lg' ? 'w-32' : size === 'md' ? 'w-24' : 'w-14'"
          :value="dragging ?? current"
          :aria-label="descriptor.name || target.label"
          :data-testid="`output-slider-${descriptor.slot}`"
          @input="dragging = Number(($event.target as HTMLInputElement).value)"
          @change="setValue(Number(($event.target as HTMLInputElement).value))"
      />
      <span class="min-w-[2rem] text-right font-mono font-normal text-gray-300">{{ +(dragging ?? current).toFixed(target.max >= 10 ? 0 : 2) }}{{ target.unit }}</span>
    </template>
    <template v-else-if="target?.control === 'color'">
      <input
          type="color"
          class="h-5 w-8 cursor-pointer rounded border border-gray-500 bg-transparent p-0"
          :value="picking ?? currentColor"
          :aria-label="descriptor.name || target.label"
          :data-testid="`output-color-${descriptor.slot}`"
          @input="picking = ($event.target as HTMLInputElement).value"
          @change="setColor(($event.target as HTMLInputElement).value)"
      />
    </template>
  </span>
</template>
