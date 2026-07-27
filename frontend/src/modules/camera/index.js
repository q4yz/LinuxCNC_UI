import { defineAsyncComponent } from "vue";

import manifest from "./manifest.js";

// Keep component imports lazy so the camera module remains removable and
// the registry can inspect this entrypoint outside Vite-based environments.
const CameraViewer = defineAsyncComponent(
  () => import("./components/CameraViewer.vue"),
);
const CameraSettings = defineAsyncComponent(
  () => import("./components/CameraSettings.vue"),
);

export default {
  manifest,
  sidebar: manifest.sidebar,
  settingsPanel: CameraSettings,
  onLoad() {
    // Pinia state is initialized lazily by the viewer or settings panel.
  },
  onUnload() {
    // The camera stream is browser-owned and closes when its image unmounts.
  },
};

export { manifest, CameraViewer, CameraSettings };
