<script setup lang="ts">
// 3D viewer display settings. Both controls here are purely
// client-side rendering preferences (persisted in this browser's
// localStorage, not a backend settings module — there's no "viewer"
// module on the backend) so they live in their own tab rather than
// alongside the backend-persisted Camera/Machine Config/Temperature
// settings.
//
// The render-quality toggle used to live as an overlay button inside
// the viewer itself, in the top-right corner — which sits directly
// under EStopHeader's fixed, always-on-top header, making the button
// unreachable to clicks. Moving it here sidesteps that stacking
// problem entirely instead of fighting z-index against a header that
// needs to stay on top for a much better reason (the operator must
// always be able to reach E-Stop).

import { useRenderQuality } from '../../composables/useRenderQuality'
import { useViewerGridSetting } from '../../composables/useViewerGridSetting'

const { quality, setQuality } = useRenderQuality()
const { showGrid, setShowGrid } = useViewerGridSetting()
</script>

<template>
  <div class="space-y-6">
    <section class="space-y-2">
      <header>
        <h3 class="text-sm font-semibold uppercase tracking-wider text-gray-300">
          Render quality
        </h3>
        <p class="text-xs text-gray-400 mt-1">
          Controls the 3D toolpath viewer's WebGL renderer. High uses
          antialiasing and your display's full pixel density — nicer
          edges, more work per frame. Low disables antialiasing and
          caps the pixel density at 1x, trading some visual polish for
          a lighter render on weak/GPU-less hardware. Antialiasing
          only takes effect after the viewer is next mounted (it's
          fixed when the WebGL context is created); the pixel-density
          half applies immediately.
        </p>
      </header>
      <div class="flex items-center gap-1 bg-gray-900 border border-gray-700 rounded-lg p-1 w-fit" role="radiogroup" aria-label="Render quality">
        <button
          type="button"
          role="radio"
          :aria-checked="quality === 'high'"
          class="px-3 py-1.5 text-sm rounded transition-colors"
          :class="quality === 'high' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'"
          @click="setQuality('high')"
        >
          High
        </button>
        <button
          type="button"
          role="radio"
          :aria-checked="quality === 'low'"
          class="px-3 py-1.5 text-sm rounded transition-colors"
          :class="quality === 'low' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'"
          @click="setQuality('low')"
        >
          Low
        </button>
      </div>
    </section>

    <section class="space-y-2">
      <header>
        <h3 class="text-sm font-semibold uppercase tracking-wider text-gray-300">
          Machine limits grid
        </h3>
        <p class="text-xs text-gray-400 mt-1">
          The reference grid drawn across the machine's travel envelope
          in the 3D toolpath viewer. Turning it off removes one more
          thing the viewer has to redraw every frame — the red
          boundary outline stays either way.
        </p>
      </header>
      <label class="flex cursor-pointer select-none items-center gap-2 text-sm text-gray-200">
        <input
          type="checkbox"
          :checked="showGrid"
          class="h-5 w-5 rounded border-gray-600 bg-gray-900 text-blue-500 focus:ring-blue-500"
          @change="setShowGrid(($event.target as HTMLInputElement).checked)"
        >
        Show grid
      </label>
    </section>
  </div>
</template>
