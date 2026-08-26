// Camera module entrypoint. The frontend registry imports this file
// **statically** — no lazy ``import.meta.glob`` — per the
// no-lazy-imports rule in ``.agent/STATE.md`` § 13.
//
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

import type { Component } from "vue";
import manifest from "./manifest";
import CameraViewer from "./components/CameraViewer.vue";
import CameraSettings from "./components/CameraSettings.vue";

// ``core/modules/protocols.ts`` carries the canonical JSDoc
// typedefs for the module surface. We re-declare the ``onLoad``
// context shape here so this file is self-contained until
// ``protocols.ts`` is converted to real TS interfaces.
interface ModuleContext {
  id: string;
  eventBus: unknown;
  telemetryBus: unknown;
  settings: unknown;
}

interface CameraModule {
  manifest: typeof manifest;
  sidebar: typeof manifest.sidebar;
  mainView: Component;
  settingsPanel: Component;
  onLoad: (ctx: ModuleContext) => void;
  onUnload: () => void;
}

const cameraModule: CameraModule = {
  manifest,
  sidebar: manifest.sidebar,
  settingsPanel: CameraSettings,
  mainView: CameraViewer,
  onLoad(_ctx: ModuleContext) {
    // Pinia state is initialised eagerly when the dashboard mounts
    // via the module's store import.
  },
  onUnload() {
    // The camera stream is browser-owned and closes when its image unmounts.
  },
};

export default cameraModule;

export { manifest, CameraViewer, CameraSettings };