// Macros module entrypoint. The frontend registry imports this file
// lazily and consumes the default export. The component contract
// matches the other modules in ``frontend/src/modules/``:
//
//   * ``manifest``   — id + title + settingsPanel flag.
//   * ``onLoad``     — no-op (no telemetry, no background work).
//   * ``onUnload``   — no-op (state lives inside the Pinia store).
//   * ``settingsPanel`` — points at ``MacroManagerPanel.vue`` so the
//     future Settings view (and tests) can mount it directly.
//
// ``store.js`` is intentionally not eagerly imported here — modules
// discover the store via the lazy ``useMacrosStore()`` factory from
// inside the panels, which dodges the Pinia active-instance timing
// trap documented in ``.agent/STATE.md`` § 4. The two components
// are re-exported so the registry's lazy ``import.meta.glob`` in
// ``DashboardView.vue`` can resolve them by name.

import manifest from "./manifest.js";
import MacroPanel from "./components/MacroPanel.vue";
import MacroManagerPanel from "./components/MacroManagerPanel.vue";

export default {
  manifest,
  onLoad(/* ctx */) {
    // Fire-and-forget pattern: the dashboard panel calls
    // ``store.loadList()`` inside ``onMounted``. We deliberately do
    // not eagerly populate the cache so an unmounted module never
    // hits the backend.
  },
  onUnload() {
    // No timers or sockets to release; Pinia tears the store down
    // with the parent scope.
  },
  // Direct component pointer — the registry exposes this so callers
  // that need to embed the manager panel can do so without
  // ``import.meta.glob`` (e.g. ``EditorView.vue``).
  settingsPanel: MacroManagerPanel,
};

export {
  manifest,
  MacroPanel,
  MacroManagerPanel,
};
