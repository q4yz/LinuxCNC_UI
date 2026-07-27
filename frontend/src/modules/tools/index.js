// Tools module entrypoint.
//
// Mirrors the conventions used by the temperature / camera
// modules. The frontend registry
// (``frontend/src/core/modules/registry.js``) imports this file
// via ``import.meta.glob`` and consumes the default export.
//
// The store is **lazily** initialised on first
// ``useToolStore()`` call inside ``ToolPanel.vue``. We
// deliberately do not call the store factory from ``onLoad``
// because the registry boots modules as part of ``main.js`` and
// the timing of ``app.use(pinia)`` relative to module
// ``onLoad`` is fragile — Pinia 3.x's ``useStore`` reads
// ``pinia._s`` and throws ``Cannot read properties of undefined
// (reading 'has')`` when ``activePinia`` has not yet been wired
// through Vite's pre-bundled Pinia instance. Letting the panel
// trigger the first call sidesteps that race entirely
// (MODULE_SYSTEM_ROADMAP.md § 12 Gotcha #1).

import manifest from "./manifest.js";
import ToolPanel from "./components/ToolPanel.vue";

export default {
  manifest,
  onLoad(/* ctx */) {
    // No-op. The store factory runs the first time the panel
    // component calls ``useToolStore()``. See the long-form
    // comment above for the boot-timing rationale.
  },
  onUnload() {
    // Pinia tears the store down with the parent scope, so
    // explicit cleanup is not required here. Kept as a no-op
    // for the contract.
  },
};

export { manifest, ToolPanel };