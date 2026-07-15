// Temperature module entrypoint.
//
// The frontend registry (`frontend/src/core/modules/registry.js`)
// imports this file via ``import.meta.glob`` and consumes the
// default export. The default export follows the
// ``FrontendModule`` contract documented in
// ``.agent/contracts/frontend-module.md``.
//
// The ``onLoad`` hook wires up the module-scoped Pinia store. We
// intentionally do **not** start the polling loop from ``onLoad`` —
// the store's own ``onScopeDispose`` hook stops it automatically
// when the pinia scope tears down. The store lazily initialises on
// first ``useTemperatureStore()`` call inside the panel component.
//
// References:
//   * MODULE_SYSTEM_ROADMAP.md § 12 Gotcha #1 — lazy imports.
//   * MODULE_SYSTEM_ROADMAP.md § 12 Gotcha #2 — store id naming.

import manifest from "./manifest.js";
import TemperaturePanel from "./components/TemperaturePanel.vue";
import { useTemperatureStore } from "./store.js";

export default {
  manifest,
  // Sidebar entry is not contributed by this module — temperature
  // lives inside the dashboard grid, not as a top-level nav item.
  onLoad(ctx) {
    // Touch the store so its bus subscription / settings timer
    // spin up immediately, regardless of whether the panel ever
    // renders (e.g. when only the Settings tab is open).
    useTemperatureStore(ctx.id);
  },
  onUnload() {
    // Pinia tears the store down with the parent scope, so explicit
    // cleanup is not required here. Kept as a no-op for the
    // contract.
  },
};

export { manifest, TemperaturePanel, useTemperatureStore };
