<template>

  <div class="rounded-lg bg-gray-800 border border-gray-700">



    <div v-if="title" class="bg-gray-700/50 px-4 py-3 border-b border-gray-600 flex items-center justify-between">
      <h2 class="font-semibold text-gray-300 uppercase tracking-wider text-sm">
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
import { onBeforeUnmount, onMounted, ref } from 'vue';

const props = withDefaults(
  defineProps<{
    title?: string;
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
  }>(),
  {
    title: '',
    footer: '',
    stagger: true,
  },
);

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
</script>
