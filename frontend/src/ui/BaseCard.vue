<template>

  <div class="rounded-lg bg-gray-800 border border-gray-700" :style="cardStyle">



    <div
        v-if="title"
        ref="header"
        class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex items-center justify-between"
        :style="headerStyle"
    >
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm flex items-center gap-2">
        <Icon v-if="icon" :name="icon" />
        {{ title }}
      </h2>


      <div class="flex items-center space-x-2">
        <slot name="header-actions" />
      </div>
    </div>
    <div class="flex-1 min-h-0">
      <slot v-if="ready" />
      <div v-else class="p-4 space-y-2 animate-pulse" aria-hidden="true" data-test="basecard-skeleton">
        <div class="h-3 w-2/3 rounded bg-gray-700"></div>
        <div class="h-3 w-1/2 rounded bg-gray-700"></div>
      </div>
    </div>


    <div v-if="footer || $slots['footer-actions']" class="bg-gray-700/30 px-4 py-3 flex justify-between text-sm text-gray-400">
      <span v-if="footer"> {{ footer }}</span>
      <div class="flex items-center space-x-2">
        <slot name="footer-actions" />
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import Icon from './Icon.vue';
import { estopBox, estopOverlap, scrollTopOf } from './estopClearance';

const props = withDefaults(
  defineProps<{
    title?: string;
    // ``Icon`` name shown before the title (an SVG — not an emoji,
    // which Linux renders as a blank box without an emoji font).
    icon?: string;
    footer?: string;
    // Opt out of the staggered reveal below. Needed for a card whose
    // slot content is itself just a placeholder that something else
    // depends on existing synchronously right after mount — e.g. a
    // Teleport target div another component moves real content into
    // (see DashboardView.vue's "Toolpath" card). Staggering a card
    // like that defers something another part of the app assumes is
    // already there, and there's no actual heavy work in the slot to
    // spread out in the first place.
    stagger?: boolean;
    // Placeholder height (px) reserved for content-visibility's
    // off-screen skip, below. Card heights vary wildly across
    // consumers (a small settings row vs. the 600px toolpath viewer),
    // and ``contain-intrinsic-size`` needs *some* estimate to reserve
    // scroll space for a card the browser hasn't measured yet. A tall
    // card should pass its own estimate; the default suits most of
    // the smaller panels. ``auto`` remembers the real measured height
    // after the card is first shown, so a mismatched guess only ever
    // costs one layout jump the first time that card scrolls into
    // view — not a running cost.
    minHeight?: number;
  }>(),
  {
    title: '',
    footer: '',
    stagger: true,
    minHeight: 220,
  },
);

// content-visibility: auto lets the browser skip layout and paint
// entirely for a card that's scrolled out of view — on a GPU-less
// target, scrolling past a long stack of cards (the Dashboard) means
// less work competing for the same software rasterizer on every
// scroll frame. It only takes effect while a card is NOT currently
// visible: a fully on-screen card (including a modal — always
// visible when shown) renders exactly as before, so this carries no
// risk to anything (dropdowns, modals) that visually escapes its own
// card's box while shown.
const cardStyle = computed(() => ({
  contentVisibility: 'auto' as const,
  containIntrinsicSize: `auto ${props.minHeight}px`,
}));

// Every dashboard panel wraps itself in BaseCard, and several of
// them (the WebGL viewer, the ECharts temperature chart, the file
// lists) are expensive to actually construct. When they're all
// gated behind the same MachineGate ref, going online flips every
// one of those v-if branches in the same synchronous render pass —
// one long blocking task that stalls whatever click the operator
// just made. Staggering each card's own slot content by a small
// random delay turns that one long task into several short ones:
// each reveal runs as its own timer callback, so the browser gets a
// chance to paint between them instead of doing all the work in a
// single frame.
//
// A random draw (rather than a shared round-robin queue) needs no
// coordination between cards — no registry, no "is this a new burst
// or a stale queue" bookkeeping — at the cost of occasionally having
// two cards land in the same task. That's an acceptable trade: even
// a collision between two cards is still strictly better than every
// card mounting together, which is today's baseline. 15ms keeps the
// whole dashboard settled almost immediately.
const STAGGER_MAX_MS = 15;
const ready = ref(!props.stagger);
let revealTimer: ReturnType<typeof setTimeout> | null = null;

onMounted(() => {
  if (!props.stagger) return;
  revealTimer = setTimeout(() => {
    revealTimer = null;
    ready.value = true;
  }, Math.random() * STAGGER_MAX_MS);
});

onBeforeUnmount(() => {
  if (revealTimer !== null) clearTimeout(revealTimer);
});

// The top-right card's header sits under the fixed E-stop box (page
// scrolled to the top): its right-hand buttons move left to clear it.
// Re-measured whenever the header's size changes (layout, a kept-alive
// view shown again) and on window resize.
const header = ref<HTMLElement | null>(null);
const estopShift = ref(0);
const HEADER_PADDING_PX = 16; // px-4
const headerStyle = computed(() =>
  estopShift.value > 0 ? { paddingRight: `${HEADER_PADDING_PX + estopShift.value}px` } : undefined);
let headerObserver: ResizeObserver | null = null;

function measureEstop(): void {
  const el = header.value;
  const estop = estopBox();
  estopShift.value = el && estop && el.offsetParent !== null
    ? estopOverlap(el.getBoundingClientRect(), estop, scrollTopOf(el))
    : 0;
}

onMounted(() => {
  if (typeof ResizeObserver !== 'undefined' && header.value) {
    headerObserver = new ResizeObserver(measureEstop);
    headerObserver.observe(header.value);
  }
  window.addEventListener('resize', measureEstop);
  measureEstop();
});

onBeforeUnmount(() => {
  headerObserver?.disconnect();
  window.removeEventListener('resize', measureEstop);
});
</script>
