// Macros module entrypoint. The frontend registry imports this file
// lazily and consumes the default export.
//
// ``settingsPanel`` points at ``MacroManagerPanel`` so the
// future Settings view can mount the manager surface directly —
// the current surface lives inside ``EditorView`` (Machine Config
// right column) which imports the components explicitly.
//
// ``MacroPanel`` and ``MacroManagerPanel`` are re-exported so the
// registry's lazy ``import.meta.glob`` in ``DashboardView.vue`` can
// resolve them by name. ``McodePanel`` and ``McodeManagerPanel``
// are also re-exported — they live in the same module (same data
// shape, same Pinia store) but cover the LinuxCNC custom-M-code
// surface (``machine_config/m_codes/``).
//
// The store is intentionally not eagerly imported here — modules
// discover the store via the lazy ``useMacrosStore()`` factory from
// inside the panels, which dodges the Pinia active-instance timing
// trap documented in ``.agent/STATE.md`` § 4.

import manifest from "./manifest.js";
import MacroPanel from "./components/MacroPanel.vue";
import MacroManagerPanel from "./components/MacroManagerPanel.vue";
import McodePanel from "./components/McodePanel.vue";
import McodeManagerPanel from "./components/McodeManagerPanel.vue";

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
  McodePanel,
  McodeManagerPanel,
};
