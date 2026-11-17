<script setup lang="ts">
// Where to measure a guided calibration's test print.
//  * skew: the square frame seen from above, front at the bottom; corner A
//    (front left) has the solid tab. Diagonals AC, BD and the side AD.
//  * pressure_advance: the tower from the side, the height of the best
//    corners measured from the bed.
defineProps<{ figure: string }>();
</script>

<template>
  <svg
    v-if="figure === 'skew'"
    viewBox="0 0 200 170"
    class="w-full max-w-[16rem] text-gray-300"
    role="img"
    aria-label="Skew square: measure the diagonals AC and BD and the left side AD between the outer corners"
    data-testid="calibration-figure-skew"
  >
    <rect x="40" y="20" width="120" height="120" fill="none" stroke="currentColor" stroke-width="6" />
    <rect x="46" y="116" width="18" height="18" fill="currentColor" opacity="0.6" />
    <line x1="37" y1="143" x2="163" y2="17" stroke="#60a5fa" stroke-width="2" stroke-dasharray="5 3" />
    <line x1="163" y1="143" x2="37" y2="17" stroke="#f59e0b" stroke-width="2" stroke-dasharray="5 3" />
    <line x1="26" y1="143" x2="26" y2="17" stroke="#34d399" stroke-width="2" />
    <line x1="21" y1="143" x2="31" y2="143" stroke="#34d399" stroke-width="2" />
    <line x1="21" y1="17" x2="31" y2="17" stroke="#34d399" stroke-width="2" />
    <g font-size="13" font-weight="700" fill="currentColor">
      <text x="30" y="160">A</text>
      <text x="162" y="160">B</text>
      <text x="162" y="14">C</text>
      <text x="30" y="14">D</text>
    </g>
    <g font-size="10">
      <text x="112" y="62" fill="#60a5fa">AC</text>
      <text x="72" y="62" fill="#f59e0b">BD</text>
      <text x="4" y="84" fill="#34d399">AD</text>
      <text x="82" y="168" fill="currentColor" opacity="0.7">front</text>
    </g>
  </svg>

  <svg
    v-else-if="figure === 'pressure_advance'"
    viewBox="0 0 200 170"
    class="w-full max-w-[16rem] text-gray-300"
    role="img"
    aria-label="Pressure advance tower from the side: measure the height of the sharpest corners from the bed"
    data-testid="calibration-figure-pressure_advance"
  >
    <line x1="20" y1="150" x2="180" y2="150" stroke="currentColor" stroke-width="2" opacity="0.6" />
    <polygon points="60,150 60,20 130,20 130,150" fill="none" stroke="currentColor" stroke-width="3" />
    <polygon points="130,150 130,20 150,30 150,150" fill="currentColor" opacity="0.25" />
    <g stroke="currentColor" stroke-width="1" opacity="0.35">
      <line v-for="k in 12" :key="k" x1="60" :y1="150 - k * 10.8" x2="150" :y2="150 - k * 10.8" />
    </g>
    <path d="M128 112 q6 -4 0 -8 M128 104 q6 -4 0 -8" stroke="#f59e0b" stroke-width="2" fill="none" />
    <path d="M128 40 q-5 -4 0 -8 M128 32 q-5 -4 0 -8" stroke="#f59e0b" stroke-width="2" fill="none" />
    <line x1="60" y1="72" x2="150" y2="72" stroke="#34d399" stroke-width="2" />
    <line x1="40" y1="150" x2="40" y2="72" stroke="#34d399" stroke-width="2" />
    <polygon points="36,80 40,72 44,80" fill="#34d399" />
    <g font-size="10">
      <text x="4" y="115" fill="#34d399">height</text>
      <text x="154" y="76" fill="#34d399">sharp</text>
      <text x="154" y="110" fill="#f59e0b">bulge</text>
      <text x="154" y="38" fill="#f59e0b">gap</text>
      <text x="70" y="164" fill="currentColor" opacity="0.7">bed</text>
    </g>
  </svg>
</template>
