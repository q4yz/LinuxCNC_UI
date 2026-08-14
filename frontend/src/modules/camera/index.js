import manifest from "./manifest.js";

// The camera module is a hard dependency. Components are imported
// **statically** — no ``defineAsyncComponent``, no dynamic
// ``import()`` — see ``.agent/STATE.md`` § 13 and
// ``frontend/scripts/check-no-lazy-imports.mjs``.
//
// ``mainView`` is the camera module's top-level view; ``App.vue`` and
// ``router/index.js::registerModuleRoutes`` both consult it so the
// sidebar click on "Camera" lands on the same component the
// dashboard renders. We pass the same ``CameraViewer`` instance the
// dashboard already uses — no wrapper, no duplicated state — so the
// store, the stream URL and the Switch-Camera button all behave
// identically in both surfaces.
import CameraViewer from "./components/CameraViewer.vue";
import CameraSettings from "./components/CameraSettings.vue";

export default {
  manifest,
  sidebar: manifest.sidebar,
  settingsPanel: CameraSettings,
  mainView: CameraViewer,
  onLoad() {
    // Pinia state is initialised eagerly when the dashboard mounts
    // via the module's store import.
  },
  onUnload() {
    // The camera stream is browser-owned and closes when its image unmounts.
  },
};

export { manifest, CameraViewer, CameraSettings };
