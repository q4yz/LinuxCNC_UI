import { defineAsyncComponent } from "vue";

import manifest from "./manifest.js";

// Keep component imports lazy so the camera module remains removable
// and the registry can inspect this entrypoint outside Vite-based
// environments.
//
// ``mainView`` is the camera module's top-level view; ``App.vue`` and
// ``router/index.js::registerModuleRoutes`` both consult it so the
// sidebar click on "Camera" lands on the same component the
// dashboard renders. We pass the same ``CameraViewer`` instance the
// dashboard already uses — no wrapper, no duplicated state — so the
// store, the stream URL and the Switch-Camera button all behave
// identically in both surfaces.
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
  mainView: CameraViewer,
  onLoad() {
    // Pinia state is initialized lazily by the viewer or settings panel.
  },
  onUnload() {
    // The camera stream is browser-owned and closes when its image unmounts.
  },
};

export { manifest, CameraViewer, CameraSettings };
