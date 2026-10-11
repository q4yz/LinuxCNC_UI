<script setup lang="ts">
// HAL oscilloscope (debug tab). Channels are HAL pins (v-model: pin
// names); samples arrive over `/ws/hal-scope` into a non-reactive
// ScopeBuffer and are drawn on a canvas every animation frame.
//
// Bench-scope controls: run/stop + single shot, sample rate, time/div,
// trigger (source, rising/falling, level, auto/normal/off, position),
// and per channel show/hide, V/div, shift up/down, auto-scale, remove.

import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";

import { BaseButton } from "../../../ui";
import { lowerBound } from "./ScopeBuffer";
import {
  X_DIVS,
  Y_DIVS,
  autoScale,
  formatTime,
  formatValue,
  placeWindow,
  stepScale,
  type TriggerEdge,
  type TriggerMode,
  type WindowState,
} from "./scopeMath";
import { useHalScopeStream } from "./useHalScopeStream";

const pins = defineModel<string[]>({ required: true });

interface ChannelSettings {
  color: string;
  visible: boolean;
  /** Value units per division. */
  scale: number;
  /** Vertical shift in divisions (+ = up). */
  offset: number;
}

const COLORS = ["#facc15", "#22d3ee", "#f472b6", "#4ade80", "#fb923c", "#a78bfa", "#f87171", "#e5e7eb"];
const RATES = [50, 100, 200, 500, 1000];
const TIME_PER_DIV_MIN = 0.001;
const TIME_PER_DIV_MAX = 5;

const settings = reactive<Record<string, ChannelSettings>>({});
const rateHz = ref(200);
const timePerDiv = ref(0.2);
const running = ref(true);
const singleArmed = ref(false);
const trigger = reactive<{ source: string; edge: TriggerEdge; mode: TriggerMode; level: number; position: number }>({
  source: "",
  edge: "rising",
  mode: "auto",
  level: 0.5,
  position: 0.5,
});

const { buffer, status, error } = useHalScopeStream(pins, rateHz);

// --- channels ------------------------------------------------------------ //

/** Channels auto-scaled once after their first data arrived. */
const autoScaled = new Set<string>();

watch(
  pins,
  (list) => {
    list.forEach((pin, i) => {
      if (!settings[pin]) {
        const used = new Set(Object.values(settings).map((s) => s.color));
        const color = COLORS.find((c) => !used.has(c)) ?? COLORS[i % COLORS.length];
        settings[pin] = { color, visible: true, scale: 1, offset: 0 };
      }
    });
    for (const pin of Object.keys(settings)) if (!list.includes(pin)) delete settings[pin];
    if (!list.includes(trigger.source)) trigger.source = list[0] ?? "";
    autoScaled.clear();
  },
  { immediate: true },
);


function removeChannel(pin: string): void {
  pins.value = pins.value.filter((p) => p !== pin);
}

// A manual change wins over the delayed first auto-fit.
function shift(pin: string, divs: number): void {
  autoScaled.add(pin);
  settings[pin].offset = Math.round((settings[pin].offset + divs) * 100) / 100;
}

function rescale(pin: string, direction: 1 | -1): void {
  autoScaled.add(pin);
  settings[pin].scale = stepScale(settings[pin].scale, direction);
}

function fitChannel(pin: string): void {
  autoScaled.add(pin);
  const view = displayed.value ?? lastWindow;
  const times = buffer.times;
  const values = buffer.values(pin);
  const from = view ? lowerBound(times, view.start) : 0;
  const to = view ? lowerBound(times, view.end) : times.length;
  const fit = autoScale(values.slice(from, to));
  if (fit) Object.assign(settings[pin], fit);
}

function fitAll(): void {
  for (const pin of pins.value) fitChannel(pin);
}

// --- time base / run state ---------------------------------------------- //

function stepTime(direction: 1 | -1): void {
  timePerDiv.value = Math.min(TIME_PER_DIV_MAX, Math.max(TIME_PER_DIV_MIN, stepScale(timePerDiv.value, direction)));
}

function toggleRun(): void {
  running.value = !running.value;
  singleArmed.value = false;
}

function armSingle(): void {
  if (trigger.mode === "off") trigger.mode = "normal";
  singleArmed.value = true;
  running.value = true;
  lastWindow = null;
}

// --- drawing ------------------------------------------------------------- //

const canvas = ref<HTMLCanvasElement | null>(null);
const cursorX = ref<number | null>(null);
/** The view currently on screen (reactive copy for the readouts). */
const displayed = ref<WindowState | null>(null);
let lastWindow: WindowState | null = null;
let frameHandle = 0;

const span = computed(() => timePerDiv.value * X_DIVS);

function yOf(value: number, channel: ChannelSettings, height: number): number {
  const divPx = height / Y_DIVS;
  return height / 2 - (value / channel.scale + channel.offset) * divPx;
}

function drawGrid(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  ctx.fillStyle = "#030712";
  ctx.fillRect(0, 0, w, h);
  ctx.lineWidth = 1;
  for (let i = 0; i <= X_DIVS; i++) {
    const x = Math.round((i * w) / X_DIVS) + 0.5;
    ctx.strokeStyle = i === X_DIVS / 2 ? "#374151" : "#1f2937";
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }
  for (let i = 0; i <= Y_DIVS; i++) {
    const y = Math.round((i * h) / Y_DIVS) + 0.5;
    ctx.strokeStyle = i === Y_DIVS / 2 ? "#374151" : "#1f2937";
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }
}

function drawTrace(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  view: WindowState,
  values: readonly (number | null)[],
  channel: ChannelSettings,
): void {
  const times = buffer.times;
  const from = Math.max(0, lowerBound(times, view.start) - 1);
  const to = Math.min(times.length, lowerBound(times, view.end) + 1);
  const xOf = (t: number) => ((t - view.start) / (view.end - view.start)) * w;
  ctx.strokeStyle = channel.color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  let pen = false;
  // More samples than pixels: draw min/max per pixel column.
  const decimate = to - from > w * 2;
  let column = -1;
  let colMin = 0;
  let colMax = 0;
  const flush = () => {
    if (column < 0) return;
    const yMin = yOf(colMin, channel, h);
    const yMax = yOf(colMax, channel, h);
    if (!pen) ctx.moveTo(column, yMax);
    else ctx.lineTo(column, yMax);
    ctx.lineTo(column, yMin);
    pen = true;
  };
  for (let i = from; i < to; i++) {
    const v = values[i];
    if (v === null || v === undefined) {
      if (decimate) flush();
      column = -1;
      pen = false;
      continue;
    }
    const x = xOf(times[i]);
    if (decimate) {
      const px = Math.floor(x);
      if (px !== column) {
        flush();
        column = px;
        colMin = v;
        colMax = v;
      } else {
        if (v < colMin) colMin = v;
        if (v > colMax) colMax = v;
      }
      continue;
    }
    const y = yOf(v, channel, h);
    if (!pen) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
    pen = true;
  }
  if (decimate) flush();
  ctx.stroke();
}

function drawMarkers(ctx: CanvasRenderingContext2D, w: number, h: number, view: WindowState): void {
  const source = settings[trigger.source];
  if (trigger.mode !== "off" && source) {
    // Trigger position (top) + level (left edge, on the source's scale).
    const tx = trigger.position * w;
    ctx.fillStyle = "#f97316";
    ctx.beginPath();
    ctx.moveTo(tx - 5, 0);
    ctx.lineTo(tx + 5, 0);
    ctx.lineTo(tx, 7);
    ctx.fill();
    const ly = yOf(trigger.level, source, h);
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = source.color;
    ctx.globalAlpha = 0.6;
    ctx.beginPath();
    ctx.moveTo(0, ly);
    ctx.lineTo(w, ly);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
    ctx.fillStyle = source.color;
    ctx.beginPath();
    ctx.moveTo(0, ly - 5);
    ctx.lineTo(7, ly);
    ctx.lineTo(0, ly + 5);
    ctx.fill();
  }
  if (cursorX.value !== null) {
    ctx.strokeStyle = "#9ca3af";
    ctx.setLineDash([2, 3]);
    ctx.beginPath();
    ctx.moveTo(cursorX.value + 0.5, 0);
    ctx.lineTo(cursorX.value + 0.5, h);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  if (!view.triggerAt && trigger.mode !== "off") {
    ctx.fillStyle = "#9ca3af";
    ctx.font = "11px ui-monospace, monospace";
    ctx.fillText(trigger.mode === "normal" ? "WAIT" : "AUTO", w - 44, 14);
  }
}

function draw(): void {
  frameHandle = requestAnimationFrame(draw);
  const el = canvas.value;
  if (!el) return;
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, el.clientWidth);
  const h = Math.max(1, el.clientHeight);
  if (el.width !== Math.round(w * dpr) || el.height !== Math.round(h * dpr)) {
    el.width = Math.round(w * dpr);
    el.height = Math.round(h * dpr);
  }
  const ctx = el.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  drawGrid(ctx, w, h);

  if (running.value) {
    const source = trigger.source ? buffer.values(trigger.source) : null;
    const next = placeWindow(
      buffer.times,
      source,
      { span: span.value, position: trigger.position, mode: trigger.mode, edge: trigger.edge, level: trigger.level },
      lastWindow,
    );
    if (singleArmed.value && next?.triggerAt != null && next !== lastWindow) {
      running.value = false;
      singleArmed.value = false;
    }
    lastWindow = next;
  }
  const view = lastWindow;
  if (displayed.value?.start !== view?.start || displayed.value?.end !== view?.end) displayed.value = view;
  if (!view) return;

  // Fit a new channel once, after enough data to show its real range
  // (a fit on the first few samples would zoom in on a flat line).
  const times = buffer.times;
  const covered = times.length ? times[times.length - 1] - times[0] : 0;
  if (covered >= Math.min(span.value, 2)) {
    for (const pin of pins.value) {
      if (!autoScaled.has(pin) && buffer.values(pin).some((v) => v !== null)) {
        autoScaled.add(pin);
        fitChannel(pin);
      }
    }
  }
  for (const pin of pins.value) {
    const channel = settings[pin];
    if (channel?.visible) drawTrace(ctx, w, h, view, buffer.values(pin), channel);
  }
  drawMarkers(ctx, w, h, view);
}

// --- readouts (5 Hz, not per animation frame) ---------------------------- //

const readout = reactive<{ rate: number; missed: number; latest: Record<string, number | null>; atCursor: Record<string, number | null>; cursorTime: number | null }>({
  rate: 0,
  missed: 0,
  latest: {},
  atCursor: {},
  cursorTime: null,
});
let readoutTimer: ReturnType<typeof setInterval> | null = null;

function valueAt(pin: string, time: number): number | null {
  const times = buffer.times;
  const i = Math.min(lowerBound(times, time), times.length - 1);
  return i >= 0 ? buffer.values(pin)[i] ?? null : null;
}

function updateReadout(): void {
  readout.rate = buffer.effectiveRate();
  readout.missed = buffer.missed;
  const latest: Record<string, number | null> = {};
  for (const pin of pins.value) {
    const values = buffer.values(pin);
    latest[pin] = values.length ? values[values.length - 1] : null;
  }
  readout.latest = latest;
  const view = displayed.value;
  const el = canvas.value;
  if (view && el && cursorX.value !== null) {
    const time = view.start + (cursorX.value / el.clientWidth) * (view.end - view.start);
    readout.cursorTime = time - (view.triggerAt ?? view.end);
    const at: Record<string, number | null> = {};
    for (const pin of pins.value) at[pin] = valueAt(pin, time);
    readout.atCursor = at;
  } else {
    readout.cursorTime = null;
  }
}

function onPointerMove(event: PointerEvent): void {
  const el = canvas.value;
  if (!el) return;
  cursorX.value = Math.max(0, Math.min(el.clientWidth, event.offsetX));
}

onMounted(() => {
  frameHandle = requestAnimationFrame(draw);
  readoutTimer = setInterval(updateReadout, 200);
});

onBeforeUnmount(() => {
  cancelAnimationFrame(frameHandle);
  if (readoutTimer) clearInterval(readoutTimer);
});

const statusLabel = computed(() => {
  if (status.value === "streaming") return `${readout.rate.toFixed(0)} S/s`;
  if (status.value === "connecting") return "connecting…";
  if (status.value === "error") return "reconnecting…";
  return "idle";
});
</script>

<template>
  <section class="space-y-3 rounded-lg border border-gray-700 bg-gray-900 p-3" data-test="hal-scope">
    <header class="flex flex-wrap items-center gap-2 text-xs">
      <h3 class="mr-2 text-sm font-semibold text-gray-100">Oscilloscope</h3>
      <BaseButton :variant="running ? 'danger' : 'success'" size="sm" data-test="scope-run" @click="toggleRun">
        {{ running ? "Stop" : "Run" }}
      </BaseButton>
      <BaseButton variant="secondary" size="sm" data-test="scope-single" :disabled="!pins.length" @click="armSingle">
        {{ singleArmed ? "Armed…" : "Single" }}
      </BaseButton>
      <BaseButton variant="ghost" size="sm" :disabled="!pins.length" @click="fitAll">Auto-scale</BaseButton>

      <label class="ml-2 flex items-center gap-1 text-gray-400">
        Rate
        <select v-model.number="rateHz" class="rounded border border-gray-600 bg-gray-950 px-1 py-0.5 text-gray-200" data-test="scope-rate">
          <option v-for="r in RATES" :key="r" :value="r">{{ r }} Hz</option>
        </select>
      </label>

      <span class="ml-2 flex items-center gap-1 text-gray-400" data-test="scope-timebase">
        Time
        <BaseButton variant="ghost" size="sm" aria-label="Faster time base" @click="stepTime(-1)">−</BaseButton>
        <span class="w-16 text-center font-mono text-gray-200">{{ formatTime(timePerDiv) }}/div</span>
        <BaseButton variant="ghost" size="sm" aria-label="Slower time base" @click="stepTime(1)">+</BaseButton>
      </span>

      <span
        class="ml-auto rounded px-2 py-0.5 font-mono"
        :class="status === 'streaming' ? 'bg-green-900/50 text-green-300' : 'bg-gray-800 text-gray-400'"
        data-test="scope-status"
      >
        {{ statusLabel }}<template v-if="readout.missed"> · {{ readout.missed }} missed</template>
      </span>
    </header>

    <div class="flex flex-wrap items-center gap-2 text-xs text-gray-400" data-test="scope-trigger">
      <span class="font-semibold uppercase tracking-wide">Trigger</span>
      <select v-model="trigger.mode" class="rounded border border-gray-600 bg-gray-950 px-1 py-0.5 text-gray-200" data-test="scope-trigger-mode">
        <option value="auto">Auto</option>
        <option value="normal">Normal</option>
        <option value="off">Off (roll)</option>
      </select>
      <select v-model="trigger.source" :disabled="trigger.mode === 'off'" class="max-w-[14rem] rounded border border-gray-600 bg-gray-950 px-1 py-0.5 font-mono text-gray-200" data-test="scope-trigger-source">
        <option v-for="pin in pins" :key="pin" :value="pin">{{ pin }}</option>
      </select>
      <div class="flex overflow-hidden rounded border border-gray-600" role="radiogroup" aria-label="Trigger edge">
        <button
          v-for="edge in (['rising', 'falling'] as const)"
          :key="edge"
          type="button"
          role="radio"
          :aria-checked="trigger.edge === edge"
          class="px-2 py-0.5"
          :class="trigger.edge === edge ? 'bg-blue-600 text-white' : 'bg-gray-950 text-gray-400 hover:text-gray-200'"
          :data-test="`scope-edge-${edge}`"
          @click="trigger.edge = edge"
        >
          {{ edge === "rising" ? "↑ rising" : "↓ falling" }}
        </button>
      </div>
      <label class="flex items-center gap-1">
        Level
        <input v-model.number="trigger.level" type="number" step="any" class="w-20 rounded border border-gray-600 bg-gray-950 px-1 py-0.5 font-mono text-gray-200" data-test="scope-trigger-level" />
      </label>
      <label class="flex items-center gap-1">
        Position
        <input v-model.number="trigger.position" type="range" min="0" max="1" step="0.05" class="w-24" data-test="scope-trigger-position" />
      </label>
    </div>

    <div class="relative">
      <canvas
        ref="canvas"
        class="block h-72 w-full cursor-crosshair rounded border border-gray-700"
        data-test="scope-canvas"
        @pointermove="onPointerMove"
        @pointerleave="cursorX = null"
      />
      <p v-if="!pins.length" class="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-gray-500">
        Add pins with the ∿ button in the pin list.
      </p>
      <p v-if="readout.cursorTime !== null" class="pointer-events-none absolute left-2 top-2 rounded bg-gray-950/80 px-2 py-1 font-mono text-[11px] text-gray-300">
        t = {{ formatTime(readout.cursorTime) }}
      </p>
    </div>
    <p v-if="error" class="text-xs text-red-300" role="alert">{{ error }}</p>

    <ul class="space-y-1" data-test="scope-channels">
      <li
        v-for="pin in pins"
        :key="pin"
        class="flex flex-wrap items-center gap-2 rounded border border-gray-800 bg-gray-950/60 px-2 py-1 text-xs"
        :data-test="`scope-channel-${pin}`"
      >
        <input v-model="settings[pin].color" type="color" class="h-5 w-6 cursor-pointer border-0 bg-transparent p-0" :aria-label="`Colour of ${pin}`" />
        <button
          type="button"
          class="w-12 rounded border px-1 py-0.5"
          :class="settings[pin].visible ? 'border-gray-600 text-gray-200' : 'border-gray-800 text-gray-600'"
          :data-test="`scope-hide-${pin}`"
          @click="settings[pin].visible = !settings[pin].visible"
        >
          {{ settings[pin].visible ? "shown" : "hidden" }}
        </button>
        <span class="min-w-0 flex-1 truncate font-mono" :style="{ color: settings[pin].color }" :title="pin">{{ pin }}</span>

        <span class="flex items-center gap-0.5 text-gray-400">
          <BaseButton variant="ghost" size="sm" :aria-label="`Smaller scale for ${pin}`" @click="rescale(pin, -1)">−</BaseButton>
          <span class="w-20 text-center font-mono text-gray-200">{{ formatValue(settings[pin].scale) }}/div</span>
          <BaseButton variant="ghost" size="sm" :aria-label="`Larger scale for ${pin}`" @click="rescale(pin, 1)">+</BaseButton>
        </span>
        <span class="flex items-center gap-0.5 text-gray-400">
          <BaseButton variant="ghost" size="sm" :aria-label="`Shift ${pin} up`" :data-test="`scope-up-${pin}`" @click="shift(pin, 0.5)">▲</BaseButton>
          <BaseButton variant="ghost" size="sm" :aria-label="`Shift ${pin} down`" :data-test="`scope-down-${pin}`" @click="shift(pin, -0.5)">▼</BaseButton>
          <button type="button" class="w-14 font-mono text-gray-300 hover:text-white" title="Shift in divisions — click to reset" @click="settings[pin].offset = 0">
            {{ settings[pin].offset >= 0 ? "+" : "" }}{{ settings[pin].offset.toFixed(2) }}
          </button>
        </span>
        <BaseButton variant="ghost" size="sm" @click="fitChannel(pin)">Fit</BaseButton>

        <span class="w-24 text-right font-mono text-gray-100" :title="'latest value'">
          {{ formatValue(readout.cursorTime !== null ? readout.atCursor[pin] : readout.latest[pin]) }}
        </span>
        <BaseButton variant="ghost" size="sm" :aria-label="`Remove ${pin}`" :data-test="`scope-remove-${pin}`" @click="removeChannel(pin)">✕</BaseButton>
      </li>
    </ul>
  </section>
</template>
