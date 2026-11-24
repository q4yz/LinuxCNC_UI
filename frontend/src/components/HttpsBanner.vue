<script setup lang="ts">
import { computed, ref } from "vue";

const dismissed = ref(false);

const isHttp = computed(() => {
  if (typeof window === "undefined" || !window.location) {
    return false;
  }
  return window.location.protocol === "http:";
});

const visible = computed(() => isHttp.value && !dismissed.value);

const httpsUrl = computed(() => {
  if (typeof window === "undefined" || !window.location) {
    return "https://";
  }
  const { hostname, pathname, search, hash } = window.location;
  // Assumes Nginx has been updated to serve HTTPS on the default port 443
  // If you are still using 8080, change this to: `https://${hostname}:8080${pathname}${search}${hash}`
  return `https://${hostname}${pathname}${search}${hash}`;
});

function onDismiss() {
  dismissed.value = true;
}
</script>

<template>
  <div
      v-if="visible"
      data-test="https-inline-banner"
      class="relative w-full min-w-0 max-w-3xl p-4 md:p-5 bg-yellow-400 text-black rounded-xl border border-yellow-500 flex flex-wrap items-center gap-4 pr-12"
  >
    <!-- Close BaseButton (Top Right) -->
    <button
        type="button"
        @click="onDismiss"
        aria-label="Dismiss banner"
        class="absolute top-2 right-2 flex items-center justify-center w-8 h-8 rounded-md hover:bg-yellow-500 transition-colors focus:outline-none focus:ring-2 focus:ring-black"
        data-test="https-banner-close"
    >
      <span aria-hidden="true" class="text-xl font-bold leading-none">✕</span>
    </button>

    <!-- The layout follows the banner's own width, not the screen's: on the
         Config page it sits in a narrow column, so text and buttons wrap
         (flex-wrap) instead of a screen-width row that pushes the buttons
         out of the card (#129). -->
    <!-- Text Area (Left Side) -->
    <div class="min-w-0 flex-[1_1_14rem]">
      <h2 class="text-lg font-bold mb-1">Secure App Setup</h2>
      <p class="text-sm font-medium leading-relaxed">
        For standalone app usage and secure hardware features, please install the root certificate and switch to HTTPS.
      </p>
    </div>

    <!-- BaseButton Area (Right Side on desktop, stacked below on mobile) -->
    <div class="flex min-w-0 flex-[1_1_auto] flex-wrap gap-3">
      <a
          href="/cnc-root.crt"
          download="cnc-root.crt"
          class="px-4 py-2 bg-black text-yellow-400 hover:bg-gray-800 rounded-lg text-center font-bold text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-yellow-400 focus:ring-black flex-1 basis-40"
          data-test="https-banner-download"
      >
        1. Download Certificate
      </a>

      <a
          :href="httpsUrl"
          class="px-4 py-2 bg-transparent border-2 border-black text-black hover:bg-yellow-500 rounded-lg text-center font-bold text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-yellow-400 focus:ring-black flex-1 basis-40"
          data-test="https-banner-switch"
      >
        2. Open Secure App
      </a>
    </div>
  </div>
</template>