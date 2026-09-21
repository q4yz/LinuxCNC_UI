<script setup lang="ts">
// Probing panel — visual layout only, no backend wiring yet.
//
// Split-pane architecture per the design spec:
//   1. Configuration header — probe calibration + offsets (would be
//      "permanent" hardware config, saved to the backend once wired).
//   2. Cycle selector — a 3x3 grid of corner/edge probing cycles plus
//      a bore/boss (Inside/Outside) center-finder, with WCS target
//      selection and job-scoped readouts (would be "volatile" job
//      state, local-only, per the design spec).
//
// Every click handler here is intentionally a no-op — this component
// renders the interaction surface only. Wiring a handler to
// `POST /api/v1/probing/execute` (or whatever the real endpoint ends
// up being) is future work; nothing here should be read as having
// been verified against real probing macros.

import {computed, reactive, ref} from "vue";
import {BaseButton, Icon} from "../../ui";
import BaseInput from "../../ui/BaseInput.vue";

type ProbeMode = "inside" | "outside";

// --- Configuration header state (would be the "permanent" /
// hardware-config half in the design doc — local-only for now). ---
const probeDiameter = ref(4.0);
const probingFeedrate = ref(100.0);
const xOffset = ref(0.0);
const yOffset = ref(0.0);
const zOffset = ref(0.0);

function saveSettings() {
  // no-op: persistence not wired yet.
}

// --- Cycle-selector / job state (would be the "volatile" half). ---
const probeMode = ref<ProbeMode>("inside");
const isOutside = computed(() => probeMode.value === "outside");

function toggleProbeMode() {
  probeMode.value = probeMode.value === "inside" ? "outside" : "inside";
}

const WCS_OPTIONS = ["G54", "G55", "G56", "G57", "G58", "G59"] as const;
const targetWcs = ref<(typeof WCS_OPTIONS)[number]>("G54");

// Read-only job position readouts — static placeholders until the
// live DRO feed is wired in.
const xPosition = ref(0);
const yPosition = ref(0);
const zPosition = ref(0);

// Outside-mode clearance fields — the 8 fields bordering the grid,
// only shown once probeMode flips to "outside". Named by their
// position around the grid (see template grid-placement classes).
const clearances = reactive({
  topLeft: 1.0,
  topRight: 1.0,
  bottomLeft: 1.0,
  bottomRight: 1.0,
  leftTop: 1.0,
  leftBottom: 1.0,
  rightTop: 1.0,
  rightBottom: 1.0,
});

// The 8 corner/edge probing cycles. `id` is a placeholder macro name
// (`O<probe_corner> call`-shaped) for whenever this is wired up.
type CycleId =
    | "corner-tl" | "edge-top" | "corner-tr"
    | "edge-left" /* center intentionally has no cycle */ | "edge-right"
    | "corner-bl" | "edge-bottom" | "corner-br";

function triggerCycle(_id: CycleId) {
  // no-op: dispatch not wired yet — see module docstring.
}

function triggerBoreBoss() {
  // no-op: dispatch not wired yet — see module docstring.
}

// --- Grid diagram geometry --------------------------------------------
//
// Two layers, deliberately separate:
//
//   1. A 3x3 grid of full-size, always-clickable tile buttons (real
//      hit area, not a tiny dot) — this layer never moves and doesn't
//      care about Inside/Outside.
//   2. A `pointer-events-none` SVG overlay on top drawing the yellow
//      boundary line + red probe-point dots. *This* layer swaps
//      geometry with the mode:
//        - Inside (probing a hole): the yellow line is the hole wall,
//          which is *outside* the points the probe actually touches
//          — so the dots sit on the smaller ring, the yellow square
//          on the bigger one.
//        - Outside (probing a boss/block): the yellow line is the
//          part's real edge, *inside* the probe's clearance approach
//          points — dots on the bigger ring, yellow square on the
//          smaller one.
//      Corners get two dots (not one) connected by a dashed arrow —
//      a corner cycle touches two faces (X then Y), not one diagonal
//      point, so the diagram shows two touch points, not a single dot.
//      The center dot (part origin) never moves.
const GRID_SIZE = 210;
const CENTER = GRID_SIZE / 2;
const RING_INNER = 75;
const RING_OUTER = 85;
const CORNER_DOT_OFFSET = 20;

type Pt = { x: number; y: number };
type Ring = { tl: Pt; tm: Pt; tr: Pt; ml: Pt; mr: Pt; bl: Pt; bm: Pt; br: Pt };

function ringPoints(half: number): Ring {
  const c = CENTER;
  return {
    tl: {x: c - half, y: c - half},
    tm: {x: c, y: c - half},
    tr: {x: c + half, y: c - half},
    ml: {x: c - half, y: c},
    mr: {x: c + half, y: c},
    bl: {x: c - half, y: c + half},
    bm: {x: c, y: c + half},
    br: {x: c + half, y: c + half},
  };
}

const innerRing = ringPoints(RING_INNER);
const outerRing = ringPoints(RING_OUTER);

// Inside -> yellow outside the dots (yellow = outer ring, dots = inner).
// Outside -> yellow inside the dots (yellow = inner ring, dots = outer).
const yellowRing = computed<Ring>(() => (isOutside.value ? innerRing : outerRing));
const dotRing = computed<Ring>(() => (isOutside.value ? outerRing : innerRing));

type CornerId = "tl" | "tr" | "bl" | "br";
const CORNER_IDS: CornerId[] = ["tl", "tr", "bl", "br"];

// Each corner's single ring point splits into two dots offset along
// the two edges that meet there (an "L") — the two separate touches
// a real corner-finding cycle takes. Each dot gets its own arrow
// running straight from the corner point to it (one purely
// horizontal, one purely vertical — never a diagonal), shortened by
// ARROW_GAP so the arrowhead lands just short of the dot instead of
// disappearing underneath it.
function cornerDotPair(corner: CornerId, ring: Ring): { a: Pt; b: Pt } {
  const p = ring[corner];
  const dx = corner === "tl" || corner === "bl" ? CORNER_DOT_OFFSET : -CORNER_DOT_OFFSET;
  const dy = corner === "tl" || corner === "tr" ? CORNER_DOT_OFFSET : -CORNER_DOT_OFFSET;
  return {a: {x: p.x + dx, y: p.y}, b: {x: p.x, y: p.y + dy}};
}

const ARROW_GAP = 6;

function shrinkToward(from: Pt, to: Pt, gap: number): Pt {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const len = Math.hypot(dx, dy) || 1;
  const t = Math.max(0, (len - gap) / len);
  return {x: from.x + dx * t, y: from.y + dy * t};
}

const cornerDots = computed(() =>
    CORNER_IDS.map((id) => {
      const ring = dotRing.value;
      const corner = ring[id];
      const {a, b} = cornerDotPair(id, ring);

      // The point where the two inside lines meet
      const innerPivot = {x: a.x, y: b.y};

      return {
        id,
        a,
        b,
        // Outside arrows (from the outer physical corner)
        arrowToA: shrinkToward(corner, a, ARROW_GAP),
        arrowToB: shrinkToward(corner, b, ARROW_GAP),

        // Inside arrows (from the inner pivot point)
        innerPivot,
        insideArrowToA: shrinkToward(innerPivot, a, ARROW_GAP),

        corner,
      };
    }),
);

// The always-clickable 3x3 tile layer — fixed position, independent
// of the mode-dependent overlay above.
const TILES: { id: string; cycle: CycleId | null; title: string; testId: string }[] = [
  {id: "tl", cycle: "corner-tl", title: "Probe top-left corner", testId: "probe-corner-tl"},
  {id: "tm", cycle: "edge-top", title: "Probe top edge", testId: "probe-edge-top"},
  {id: "tr", cycle: "corner-tr", title: "Probe top-right corner", testId: "probe-corner-tr"},
  {id: "ml", cycle: "edge-left", title: "Probe left edge", testId: "probe-edge-left"},
  {id: "c", cycle: null, title: "Part origin", testId: "probe-origin"},
  {id: "mr", cycle: "edge-right", title: "Probe right edge", testId: "probe-edge-right"},
  {id: "bl", cycle: "corner-bl", title: "Probe bottom-left corner", testId: "probe-corner-bl"},
  {id: "bm", cycle: "edge-bottom", title: "Probe bottom edge", testId: "probe-edge-bottom"},
  {id: "br", cycle: "corner-br", title: "Probe bottom-right corner", testId: "probe-corner-br"},
];

// Percentage offsets for the outside-mode clearance fields, keyed to
// the fixed tile grid (cell centers at 35/105/175 of a 210 box) —
// independent of the ring geometry above, so these never move.
const COL_LEFT_PCT = (35 / GRID_SIZE) * 100;
const COL_RIGHT_PCT = (175 / GRID_SIZE) * 100;
const ROW_TOP_PCT = (35 / GRID_SIZE) * 100;
const ROW_BOTTOM_PCT = (175 / GRID_SIZE) * 100;
</script>

<template>
  <div class="space-y-6">
    <!-- ============================================================ -->
    <!-- 1. Configuration header                                       -->
    <!-- ============================================================ -->
    <div class="rounded-lg bg-gray-800 border border-gray-700 p-4 space-y-4">
      <div class="flex flex-wrap items-end gap-4">
        <BaseButton variant="secondary" @click="toggleProbeMode" data-testid="probe-mode-toggle">
          {{ isOutside ? "Outside" : "Inside" }}
        </BaseButton>

        <label class="text-sm text-gray-200">
          <span class="mb-1 block text-xs font-medium text-gray-400">Probe Diameter</span>
          <BaseInput type="number" step="0.01" min="0" v-model="probeDiameter" class="w-32"
                     data-testid="probe-diameter"/>
        </label>

        <label class="text-sm text-gray-200">
          <span class="mb-1 block text-xs font-medium text-gray-400">Probing Feedrate</span>
          <BaseInput type="number" step="1" min="0" v-model="probingFeedrate" class="w-32"
                     data-testid="probing-feedrate"/>
        </label>
      </div>

      <div class="flex flex-wrap items-end gap-4">
        <label class="text-sm text-gray-200">
          <span class="mb-1 block text-xs font-medium text-gray-400">X Offset</span>
          <BaseInput type="number" step="0.01" v-model="xOffset" class="w-28" data-testid="x-offset"/>
        </label>
        <label class="text-sm text-gray-200">
          <span class="mb-1 block text-xs font-medium text-gray-400">Y Offset</span>
          <BaseInput type="number" step="0.01" v-model="yOffset" class="w-28" data-testid="y-offset"/>
        </label>
        <label class="text-sm text-gray-200">
          <span class="mb-1 block text-xs font-medium text-gray-400">Z Offset</span>
          <BaseInput type="number" step="0.01" v-model="zOffset" class="w-28" data-testid="z-offset"/>
        </label>

        <BaseButton variant="primary" class="ml-auto" @click="saveSettings" data-testid="probe-save-settings">
          <template #icon>
            <Icon name="save" size="h-4 w-4"/>
          </template>
          Save Settings
        </BaseButton>
      </div>
    </div>

    <!-- ============================================================ -->
    <!-- 2. Cycle selector                                             -->
    <!-- ============================================================ -->
    <div class="rounded-lg bg-gray-800 border border-gray-700 p-4 space-y-4">
      <!-- WCS target selection -->
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs font-medium text-gray-400 uppercase tracking-wider mr-2">Target WCS</span>
        <BaseButton
            v-for="code in WCS_OPTIONS"
            :key="code"
            :variant="targetWcs === code ? 'primary' : 'secondary'"
            size="sm"
            @click="targetWcs = code"
            :data-testid="`wcs-${code}`"
        >
          {{ code }}
        </BaseButton>
      </div>

      <!-- Job position readouts -->
      <div class="grid grid-cols-3 gap-4 max-w-md">
        <label class="text-sm text-gray-200">
          <span class="mb-1 block text-xs font-medium text-gray-400">X Position</span>
          <div class="bg-gray-900 border border-gray-600 rounded px-3 py-2 text-gray-100" data-testid="x-position">
            {{ xPosition.toFixed(2) }}
          </div>
        </label>
        <label class="text-sm text-gray-200">
          <span class="mb-1 block text-xs font-medium text-gray-400">Y Position</span>
          <div class="bg-gray-900 border border-gray-600 rounded px-3 py-2 text-gray-100" data-testid="y-position">
            {{ yPosition.toFixed(2) }}
          </div>
        </label>
        <label class="text-sm text-gray-200">
          <span class="mb-1 block text-xs font-medium text-gray-400">Z Position</span>
          <div class="bg-gray-900 border border-gray-600 rounded px-3 py-2 text-gray-100" data-testid="z-position">
            {{ zPosition.toFixed(2) }}
          </div>
        </label>
      </div>

      <!-- Grid + bore/boss selector -->
      <div class="flex flex-wrap items-center gap-8 pt-2">
        <!-- Bore / Boss (Inside/Outside center-finder) -->
        <button
            type="button"
            class="shrink-0 h-20 w-20 rounded-full border-2 border-yellow-400 bg-gray-900 flex items-center justify-center hover:bg-gray-800/60 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
            title="Find bore / boss center"
            data-testid="probe-bore-boss"
            @click="triggerBoreBoss"
        >
          <span class="h-2.5 w-2.5 rounded-full bg-red-500" aria-hidden="true"></span>
        </button>

        <!-- 3x3 cycle grid — two layers: always-clickable tile buttons
             underneath, and a decorative (pointer-events-none) overlay
             on top drawing the yellow boundary + probe-point dots. The
             overlay's geometry swaps with Inside/Outside (see script). -->
        <div
            class="relative shrink-0"
            :style="{ width: `${GRID_SIZE}px`, height: `${GRID_SIZE}px` }"
            :class="isOutside ? 'mx-16 my-9' : ''"
        >
          <!-- Tile layer: the actual pressable surface, one button per
               cell, fixed regardless of mode. -->
          <div class="absolute inset-0 grid grid-cols-3 grid-rows-3 rounded overflow-hidden border border-gray-700">
            <button
                v-for="tile in TILES"
                :key="tile.id"
                type="button"
                class="bg-gray-900 border border-gray-700/50 transition-colors focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500"
                :class="tile.cycle ? 'hover:bg-gray-800/80 cursor-pointer' : 'cursor-default'"
                :disabled="!tile.cycle"
                :title="tile.title"
                :data-testid="tile.testId"
                @click="tile.cycle && triggerCycle(tile.cycle)"
            ></button>
          </div>

          <!-- Overlay layer: decorative only, never intercepts clicks. -->
          <svg
              :viewBox="`0 0 ${GRID_SIZE} ${GRID_SIZE}`" :width="GRID_SIZE" :height="GRID_SIZE"
              class="absolute inset-0 pointer-events-none"
          >
            <defs>
              <marker id="probe-arrow" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="7" markerHeight="7"
                      orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 Z" fill="#f9fafb"/>
              </marker>
            </defs>

            <!-- The part boundary — outside the dots in Inside mode
                 (it's the hole wall), inside them in Outside mode
                 (it's the block's real edge; the dots are the probe's
                 further-out clearance approach points). -->
            <rect
                :x="yellowRing.tl.x" :y="yellowRing.tl.y"
                :width="yellowRing.br.x - yellowRing.tl.x" :height="yellowRing.br.y - yellowRing.tl.y"
                fill="none" stroke="#facc15" stroke-width="2.5"
            />

            <!-- Edge-midpoint probe points (single dot each). -->
            <circle :cx="dotRing.tm.x" :cy="dotRing.tm.y" r="4" fill="#ef4444"/>
            <circle :cx="dotRing.ml.x" :cy="dotRing.ml.y" r="4" fill="#ef4444"/>
            <circle :cx="dotRing.mr.x" :cy="dotRing.mr.y" r="4" fill="#ef4444"/>
            <circle :cx="dotRing.bm.x" :cy="dotRing.bm.y" r="4" fill="#ef4444"/>

            <!-- Part origin — fixed at center regardless of mode. -->
            <circle :cx="CENTER" :cy="CENTER" r="3.5" fill="#ef4444"/>

            <!-- Corner probe points — two dots (the two faces touched
                 near that corner), each reached by its own straight,
                 axis-aligned arrow from the corner point — one purely
                 vertical, one purely horizontal, never diagonal. -->
            <g v-for="pair in cornerDots" :key="pair.id">

              <template v-if="isOutside">
                <!-- Outside wrap-around path: B -> Corner -> A -->
                <line
                    :x1="pair.arrowToB.x" :y1="pair.arrowToB.y" :x2="pair.corner.x" :y2="pair.corner.y"
                    stroke="#f9fafb" stroke-width="2" stroke-dasharray="5,3"
                />
                <line
                    :x1="pair.corner.x" :y1="pair.corner.y" :x2="pair.arrowToA.x" :y2="pair.arrowToA.y"
                    stroke="#f9fafb" stroke-width="2" stroke-dasharray="5,3"
                    marker-end="url(#probe-arrow)"
                />
              </template>

              <template v-else>
                <!-- Inside pocket path: B (wall) -> Inner Pivot -> A (wall) -->
                <line
                    :x1="pair.b.x" :y1="pair.b.y" :x2="pair.innerPivot.x" :y2="pair.innerPivot.y"
                    stroke="#f9fafb" stroke-width="2" stroke-dasharray="5,3"
                />
                <line
                    :x1="pair.innerPivot.x" :y1="pair.innerPivot.y" :x2="pair.insideArrowToA.x"
                    :y2="pair.insideArrowToA.y"
                    stroke="#f9fafb" stroke-width="2" stroke-dasharray="5,3"
                    marker-end="url(#probe-arrow)"
                />
              </template>

              <!-- The touch dots must be rendered regardless of Inside/Outside mode -->
              <circle :cx="pair.a.x" :cy="pair.a.y" r="4" fill="#ef4444"/>
              <circle :cx="pair.b.x" :cy="pair.b.y" r="4" fill="#ef4444"/>

            </g>
          </svg>

          <!-- Outside-mode clearance fields, positioned around the
               diagram and only rendered when Outside is active. -->
          <template v-if="isOutside">
            <div class="absolute -top-9 -translate-x-1/2" :style="{ left: `${COL_LEFT_PCT}%` }">
              <BaseInput type="number" step="0.01" v-model="clearances.topLeft" class="w-14 text-xs px-1 py-1"
                         data-testid="clearance-top-left"/>
            </div>
            <div class="absolute -top-9 -translate-x-1/2" :style="{ left: `${COL_RIGHT_PCT}%` }">
              <BaseInput type="number" step="0.01" v-model="clearances.topRight" class="w-14 text-xs px-1 py-1"
                         data-testid="clearance-top-right"/>
            </div>
            <div class="absolute -bottom-9 -translate-x-1/2" :style="{ left: `${COL_LEFT_PCT}%` }">
              <BaseInput type="number" step="0.01" v-model="clearances.bottomLeft" class="w-14 text-xs px-1 py-1"
                         data-testid="clearance-bottom-left"/>
            </div>
            <div class="absolute -bottom-9 -translate-x-1/2" :style="{ left: `${COL_RIGHT_PCT}%` }">
              <BaseInput type="number" step="0.01" v-model="clearances.bottomRight" class="w-14 text-xs px-1 py-1"
                         data-testid="clearance-bottom-right"/>
            </div>
            <div class="absolute -left-16 -translate-y-1/2" :style="{ top: `${ROW_TOP_PCT}%` }">
              <BaseInput type="number" step="0.01" v-model="clearances.leftTop" class="w-14 text-xs px-1 py-1"
                         data-testid="clearance-left-top"/>
            </div>
            <div class="absolute -left-16 -translate-y-1/2" :style="{ top: `${ROW_BOTTOM_PCT}%` }">
              <BaseInput type="number" step="0.01" v-model="clearances.leftBottom" class="w-14 text-xs px-1 py-1"
                         data-testid="clearance-left-bottom"/>
            </div>
            <div class="absolute -right-16 -translate-y-1/2" :style="{ top: `${ROW_TOP_PCT}%` }">
              <BaseInput type="number" step="0.01" v-model="clearances.rightTop" class="w-14 text-xs px-1 py-1"
                         data-testid="clearance-right-top"/>
            </div>
            <div class="absolute -right-16 -translate-y-1/2" :style="{ top: `${ROW_BOTTOM_PCT}%` }">
              <BaseInput type="number" step="0.01" v-model="clearances.rightBottom" class="w-14 text-xs px-1 py-1"
                         data-testid="clearance-right-bottom"/>
            </div>
          </template>
        </div>
      </div>

      <p class="text-xs text-blue-300/80 italic">All values in millimeters</p>
    </div>
  </div>
</template>

<style scoped>
</style>
