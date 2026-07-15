// Temperature module entrypoint.
//
// The frontend registry (`frontend/src/core/modules/registry.js`)
// imports this file via ``import.meta.glob`` and consumes the
// default export. The default export follows the
// ``FrontendModule`` contract documented in
// ``.agent/contracts/frontend-module.md``.
//
// The store is **lazily** initialised on first ``useTemperatureStore()``
// call inside ``TemperaturePanel.vue``. We deliberately do not call
// the store factory from ``onLoad`` because:
//
//   1. The registry boots modules as part of ``main.js`` and the
//      timing of ``app.use(pinia)`` relative to module ``onLoad`` is
//      fragile — Pinia 3.x's ``useStore`` reads ``pinia._s`` and
//      throws ``Cannot read properties of undefined (reading 'has')``
//      when ``activePinia`` has not yet been wired through Vite's
//      pre-bundled Pinia instance. Letting the panel trigger the
//      first call sidesteps that race entirely.
//   2. If the user only ever opens the Settings tab (no temperature
//      panel), there is no reason to start the polling loop.
//
// References:
//   * MODULE_SYSTEM_ROADMAP.md § 12 Gotcha #1 — lazy imports.
//   * MODULE_SYSTEM_ROADMAP.md § 12 Gotcha #2 — store id naming.

import manifest from "./manifest.js";
import TemperaturePanel from "./components/TemperaturePanel.vue";

export default {
  manifest,
  // Sidebar entry is not contributed by this module — temperature
  // lives inside the dashboard grid, not as a top-level nav item.
  onLoad(/* ctx */) {
    // No-op. The store factory runs the first time the panel
    // component calls ``useTemperatureStore()``. See the long-form
    // comment above for the boot-timing rationale.
  },
  onUnload() {
    // Pinia tears the store down with the parent scope, so explicit
    // cleanup is not required here. Kept as a no-op for the
    // contract.
  },
};

export { manifest, TemperaturePanel };
