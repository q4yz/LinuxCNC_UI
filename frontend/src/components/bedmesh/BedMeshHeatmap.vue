<script setup lang="ts">
// A bed mesh as a heatmap image: the bed seen from above (Y up, front-left
// corner bottom-left), drawn on a canvas in the bed's proportions. Every pixel
// is the Z offset interpolated bilinearly between the probe points, coloured
// on a gradient from blue (bed lower) over grey (0) to red (bed higher),
// scaled to the mesh's largest deviation. The dots are the probe points.
// Click a spot to read its offset; with ``editable`` the nearest probe point
// of the clicked spot can be changed.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { BedMeshGrid } from "../../facades/bedMeshFacade";
import { GRADIENT_CSS, gradientColor, interpolate, maxDeviation, nearestPoint } from "./bedMeshMath";

const props = defineProps<{ grid: BedMeshGrid; editable?: boolean }>();
const emit = defineEmits<{ (e: "update:cell", row: number, col: number, value: number): void }>();

const PAD = { left: 52, right: 14, top: 12, bottom: 30 };
const MAX_PLOT_HEIGHT = 520;
// CSS pixels per interpolated sample: the image is computed at this lower resolution and
// smoothed when scaled up, which looks the same for a bilinear surface and costs ~1/16 per pixel
const SAMPLE_PX = 4;

const wrap = ref<HTMLDivElement | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const width = ref(640);
let observer: ResizeObserver | null = null;

const values = computed(() => props.grid.z.flat());
const maxAbs = computed(() => maxDeviation(props.grid));
const stats = computed(() => {
  const v = values.value;
  const min = Math.min(...v);
  const max = Math.max(...v);
  return { min, max, range: max - min };
});

const xMin = computed(() => props.grid.xs[0] ?? 0);
const xMax = computed(() => props.grid.xs[props.grid.xs.length - 1] ?? 1);
const yMin = computed(() => props.grid.ys[0] ?? 0);
const yMax = computed(() => props.grid.ys[props.grid.ys.length - 1] ?? 1);

// The plot area in CSS pixels, in the bed's proportions, at most MAX_PLOT_HEIGHT high.
const layout = computed(() => {
  const spanX = xMax.value - xMin.value || 1;
  const spanY = yMax.value - yMin.value || 1;
  let pw = Math.max(120, width.value - PAD.left - PAD.right);
  let ph = (pw * spanY) / spanX;
  if (ph > MAX_PLOT_HEIGHT) {
    ph = MAX_PLOT_HEIGHT;
    pw = (ph * spanX) / spanY;
  }
  pw = Math.round(pw);
  ph = Math.round(ph);
  return { pw, ph, w: PAD.left + pw + PAD.right, h: PAD.top + ph + PAD.bottom };
});

// bed mm <-> CSS pixels on the canvas
function toPx(x: number, y: number): [number, number] {
  const { pw, ph } = layout.value;
  const fx = (x - xMin.value) / (xMax.value - xMin.value || 1);
  const fy = (y - yMin.value) / (yMax.value - yMin.value || 1);
  return [PAD.left + fx * pw, PAD.top + ph - fy * ph];
}

function toBed(px: number, py: number): [number, number] {
  const { pw, ph } = layout.value;
  return [
    xMin.value + ((px - PAD.left) / pw) * (xMax.value - xMin.value),
    yMin.value + ((PAD.top + ph - py) / ph) * (yMax.value - yMin.value),
  ];
}

// the clicked spot (bed mm) and the one under the mouse
const picked = ref<{ x: number; y: number } | null>(null);
const hover = ref<{ x: number; y: number } | null>(null);

function spotInfo(spot: { x: number; y: number } | null) {
  if (!spot) return null;
  const point = nearestPoint(props.grid, spot.x, spot.y);
  return {
    ...spot,
    z: interpolate(props.grid, spot.x, spot.y),
    point,
    pointX: props.grid.xs[point.col],
    pointY: props.grid.ys[point.row],
    pointZ: props.grid.z[point.row][point.col],
  };
}
const pickedInfo = computed(() => spotInfo(picked.value));
const hoverInfo = computed(() => spotInfo(hover.value));

function eventSpot(event: MouseEvent): { x: number; y: number } | null {
  const el = canvas.value;
  if (!el) return null;
  const rect = el.getBoundingClientRect();
  const px = event.clientX - rect.left;
  const py = event.clientY - rect.top;
  const { pw, ph } = layout.value;
  if (px < PAD.left || px > PAD.left + pw || py < PAD.top || py > PAD.top + ph) return null;
  const [x, y] = toBed(px, py);
  return { x, y };
}

function onClick(event: MouseEvent) {
  const spot = eventSpot(event);
  if (spot) picked.value = spot;
}

function onMove(event: MouseEvent) {
  hover.value = eventSpot(event);
}

function fmt(v: number, digits = 3): string {
  return (v >= 0 ? "+" : "") + v.toFixed(digits);
}

function onInput(event: Event) {
  const info = pickedInfo.value;
  const value = Number((event.target as HTMLInputElement).value);
  if (info && Number.isFinite(value)) emit("update:cell", info.point.row, info.point.col, value);
}

// ---------------------------------------------------------------- drawing

// The heat image, recomputed only when the mesh or the size changes (not on a click).
let heatImage: HTMLCanvasElement | null = null;

function buildImage() {
  if (!props.grid.xs.length || !props.grid.ys.length) {
    heatImage = null;
    return;
  }
  const { pw, ph } = layout.value;
  const iw = Math.max(2, Math.ceil(pw / SAMPLE_PX));
  const ih = Math.max(2, Math.ceil(ph / SAMPLE_PX));
  const off = heatImage ?? document.createElement("canvas");
  off.width = iw;
  off.height = ih;
  const octx = off.getContext("2d");
  if (!octx) return;
  const image = octx.createImageData(iw, ih);
  const spanX = xMax.value - xMin.value;
  const spanY = yMax.value - yMin.value;
  // samples on the edges too, so the scaled image reaches the mesh corners
  for (let j = 0; j < ih; j++) {
    const y = yMax.value - (j / (ih - 1)) * spanY;
    for (let i = 0; i < iw; i++) {
      const x = xMin.value + (i / (iw - 1)) * spanX;
      const [r, g, b] = gradientColor(interpolate(props.grid, x, y), maxAbs.value);
      const o = 4 * (j * iw + i);
      image.data[o] = r;
      image.data[o + 1] = g;
      image.data[o + 2] = b;
      image.data[o + 3] = 255;
    }
  }
  octx.putImageData(image, 0, 0);
  heatImage = off;
}

function draw() {
  const el = canvas.value;
  if (!el || !heatImage) return;
  const { pw, ph, w, h } = layout.value;
  const dpr = window.devicePixelRatio || 1;
  if (el.width !== Math.round(w * dpr) || el.height !== Math.round(h * dpr)) {
    el.width = Math.round(w * dpr);
    el.height = Math.round(h * dpr);
    el.style.width = `${w}px`;
    el.style.height = `${h}px`;
  }
  const ctx = el.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  // the cached image, smoothed while scaled up; the half sample at each side maps
  // the edge samples onto the mesh edges
  const sx = pw / (heatImage.width - 1);
  const sy = ph / (heatImage.height - 1);
  ctx.save();
  ctx.beginPath();
  ctx.rect(PAD.left, PAD.top, pw, ph);
  ctx.clip();
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(heatImage, PAD.left - sx / 2, PAD.top - sy / 2, pw + sx, ph + sy);
  ctx.restore();

  // frame, axis labels at the probe coordinates (thinned out when they would overlap)
  ctx.strokeStyle = "rgba(156, 163, 175, 0.6)";
  ctx.lineWidth = 1;
  ctx.strokeRect(PAD.left - 0.5, PAD.top - 0.5, pw + 1, ph + 1);
  ctx.fillStyle = "#9ca3af";
  ctx.font = "11px ui-monospace, monospace";
  const stepX = Math.max(1, Math.ceil(36 / (pw / Math.max(1, props.grid.xs.length - 1))));
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  props.grid.xs.forEach((x, col) => {
    if (col % stepX && col !== props.grid.xs.length - 1) return;
    ctx.fillText(String(x), toPx(x, yMin.value)[0], PAD.top + ph + 6);
  });
  const stepY = Math.max(1, Math.ceil(18 / (ph / Math.max(1, props.grid.ys.length - 1))));
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  props.grid.ys.forEach((y, row) => {
    if (row % stepY && row !== props.grid.ys.length - 1) return;
    ctx.fillText(String(y), PAD.left - 6, toPx(xMin.value, y)[1]);
  });

  // probe points, the one nearest to the clicked spot ringed
  const sel = pickedInfo.value?.point;
  props.grid.ys.forEach((y, row) =>
    props.grid.xs.forEach((x, col) => {
      const [px, py] = toPx(x, y);
      ctx.beginPath();
      ctx.arc(px, py, 2.5, 0, 2 * Math.PI);
      ctx.fillStyle = "rgba(17, 24, 39, 0.75)";
      ctx.fill();
      if (sel && sel.row === row && sel.col === col) {
        ctx.beginPath();
        ctx.arc(px, py, 7, 0, 2 * Math.PI);
        ctx.strokeStyle = "#111827";
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    }),
  );

  // the clicked spot: crosshair
  if (picked.value) {
    const [px, py] = toPx(picked.value.x, picked.value.y);
    ctx.strokeStyle = "#111827";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(px - 9, py);
    ctx.lineTo(px + 9, py);
    ctx.moveTo(px, py - 9);
    ctx.lineTo(px, py + 9);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(px, py, 4, 0, 2 * Math.PI);
    ctx.strokeStyle = "#f9fafb";
    ctx.stroke();
  }
}

let frame = 0;
function redraw() {
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(draw);
}

// the image only for a new mesh / size, a click only redraws the overlay
watch(
  () => [props.grid, layout.value],
  () => {
    buildImage();
    redraw();
  },
  { deep: true },
);
watch(picked, redraw);

// another mesh: forget the spot
watch(
  () => props.grid.name,
  () => {
    picked.value = null;
  },
);

onMounted(async () => {
  if (wrap.value) {
    observer = new ResizeObserver(() => {
      if (wrap.value) width.value = wrap.value.clientWidth;
    });
    observer.observe(wrap.value);
    width.value = wrap.value.clientWidth;
  }
  await nextTick();
  buildImage();
  draw();
});

onBeforeUnmount(() => {
  observer?.disconnect();
  cancelAnimationFrame(frame);
});
</script>

<template>
  <div class="space-y-3" data-testid="bed-mesh-heatmap">
    <div ref="wrap" class="flex w-full justify-center">
      <canvas
        ref="canvas"
        class="cursor-crosshair"
        role="img"
        :aria-label="`Bed mesh ${grid.name}: Z offsets from ${fmt(stats.min)} to ${fmt(stats.max)} mm`"
        data-testid="bed-mesh-canvas"
        @click="onClick"
        @mousemove="onMove"
        @mouseleave="hover = null"
      ></canvas>
    </div>

    <!-- legend: the gradient, symmetric around 0 -->
    <div class="mx-auto flex max-w-md items-center gap-2 font-mono text-xs text-gray-400">
      <span>{{ fmt(-maxAbs) }}</span>
      <span class="h-3 flex-1 rounded" :style="{ background: GRADIENT_CSS }"></span>
      <span>{{ fmt(maxAbs) }} mm</span>
    </div>
    <div class="flex flex-wrap items-center justify-center gap-4 text-xs text-gray-400">
      <span>min <span class="font-mono text-blue-300">{{ fmt(stats.min) }}</span></span>
      <span>max <span class="font-mono text-red-300">{{ fmt(stats.max) }}</span></span>
      <span>range <span class="font-mono text-gray-200">{{ stats.range.toFixed(3) }}</span> mm</span>
      <span>blue lower, red higher</span>
    </div>

    <!-- the clicked spot -->
    <div class="mx-auto max-w-md rounded border border-gray-700 bg-gray-900/60 p-3 text-sm" data-testid="bed-mesh-spot">
      <template v-if="pickedInfo">
        <div class="font-mono text-gray-200">
          X {{ pickedInfo.x.toFixed(1) }} Y {{ pickedInfo.y.toFixed(1) }}:
          <span class="font-semibold">Z {{ fmt(pickedInfo.z, 4) }} mm</span>
        </div>
        <div class="mt-1 flex flex-wrap items-center gap-2 font-mono text-xs text-gray-400">
          <span>nearest probe point X {{ pickedInfo.pointX }} Y {{ pickedInfo.pointY }}:</span>
          <input
            v-if="editable"
            type="number"
            step="0.001"
            class="w-24 rounded bg-gray-800 px-1 py-0.5 text-center text-gray-100"
            :value="pickedInfo.pointZ"
            data-testid="bed-mesh-point-input"
            @change="onInput"
          />
          <span v-else>Z {{ fmt(pickedInfo.pointZ, 4) }} mm</span>
        </div>
      </template>
      <p v-else class="text-center text-xs text-gray-500">
        Click the map to see the offset at that spot{{ editable ? " and edit the nearest probe point" : "" }}.
      </p>
      <p v-if="hoverInfo" class="mt-1 text-center font-mono text-xs text-gray-500">
        under the mouse: X {{ hoverInfo.x.toFixed(1) }} Y {{ hoverInfo.y.toFixed(1) }} Z {{ fmt(hoverInfo.z, 4) }}
      </p>
    </div>
  </div>
</template>
