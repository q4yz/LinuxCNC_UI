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
  <svg
    v-else-if="figure === 'extruder_steps'"
    viewBox="0 0 200 170"
    class="w-full max-w-[16rem] text-gray-300"
    role="img"
    aria-label="Extruder steps: a mark 120 mm above the extruder inlet; after extruding 100 mm measure the remaining distance"
    data-testid="calibration-figure-extruder_steps"
  >
    <rect x="70" y="110" width="60" height="40" rx="4" fill="none" stroke="currentColor" stroke-width="3" />
    <text x="78" y="134" font-size="10" fill="currentColor">extruder</text>
    <line x1="100" y1="10" x2="100" y2="110" stroke="currentColor" stroke-width="4" opacity="0.6" />
    <line x1="92" y1="30" x2="108" y2="30" stroke="#f59e0b" stroke-width="3" />
    <text x="112" y="34" font-size="10" fill="#f59e0b">mark</text>
    <line x1="60" y1="110" x2="60" y2="30" stroke="#34d399" stroke-width="2" />
    <polygon points="56,38 60,30 64,38" fill="#34d399" />
    <text x="8" y="74" font-size="10" fill="#34d399">mark</text>
    <text x="8" y="86" font-size="9" fill="#34d399">(120)</text>
    <line x1="140" y1="110" x2="140" y2="64" stroke="#60a5fa" stroke-width="2" />
    <polygon points="136,72 140,64 144,72" fill="#60a5fa" />
    <line x1="140" y1="90" x2="140" y2="62" stroke="#f59e0b" stroke-width="1" stroke-dasharray="3 2" />
    <line x1="132" y1="62" x2="148" y2="62" stroke="#f59e0b" stroke-width="2" />
    <text x="146" y="58" font-size="9" fill="#f59e0b">mark after</text>
    <text x="146" y="80" font-size="10" fill="#60a5fa">remaining</text>
  </svg>

  <svg
    v-else-if="figure === 'flow'"
    viewBox="0 0 200 170"
    class="w-full max-w-[16rem] text-gray-300"
    role="img"
    aria-label="Flow cube: measure the thickness of one wall with calipers, above the brim"
    data-testid="calibration-figure-flow"
  >
    <polygon points="15,60 85,60 110,42 40,42" fill="none" stroke="currentColor" stroke-width="2" opacity="0.6" />
    <polygon points="15,60 15,130 85,130 85,60" fill="none" stroke="currentColor" stroke-width="3" />
    <polygon points="85,60 110,42 110,112 85,130" fill="none" stroke="currentColor" stroke-width="3" />
    <rect x="8" y="130" width="110" height="5" fill="currentColor" opacity="0.4" />
    <text x="40" y="150" font-size="9" fill="currentColor" opacity="0.7">brim (break off)</text>
    <circle cx="85" cy="90" r="9" fill="none" stroke="#f59e0b" stroke-width="1.5" />
    <line x1="94" y1="90" x2="128" y2="90" stroke="#f59e0b" stroke-width="1" stroke-dasharray="3 2" />
    <rect x="150" y="50" width="10" height="80" fill="currentColor" opacity="0.7" />
    <path d="M128 70 h20 v40 h-20 M182 70 h-20 v40 h20" stroke="#34d399" stroke-width="3" fill="none" />
    <text x="138" y="44" font-size="10" fill="#34d399">calipers</text>
    <text x="134" y="146" font-size="10" fill="#f59e0b">one wall</text>
  </svg>

  <svg
    v-else-if="figure === 'first_layer'"
    viewBox="0 0 200 170"
    class="w-full max-w-[16rem] text-gray-300"
    role="img"
    aria-label="First layer: five patches; tune the live Z offset on the middle one"
    data-testid="calibration-figure-first_layer"
  >
    <rect x="20" y="10" width="160" height="120" fill="none" stroke="currentColor" stroke-width="1" opacity="0.5" />
    <rect x="85" y="55" width="30" height="30" fill="#34d399" opacity="0.7" />
    <rect x="30" y="20" width="22" height="22" fill="currentColor" opacity="0.5" />
    <rect x="148" y="20" width="22" height="22" fill="currentColor" opacity="0.5" />
    <rect x="30" y="98" width="22" height="22" fill="currentColor" opacity="0.5" />
    <rect x="148" y="98" width="22" height="22" fill="currentColor" opacity="0.5" />
    <text x="74" y="100" font-size="10" fill="#34d399">tune here</text>
    <g font-size="9">
      <text x="20" y="142" fill="#f59e0b">too high: round lines with gaps</text>
      <text x="20" y="154" fill="#34d399">right: flat lines that touch</text>
      <text x="20" y="166" fill="#f87171">too low: rough, thin, see-through</text>
    </g>
  </svg>
</template>
