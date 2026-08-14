// Macros module entrypoint. The frontend registry imports this file
// **statically** — no lazy ``import.meta.glob`` — per the
// no-lazy-imports rule in ``.agent/STATE.md`` § 13.
//
// ``MacroPanel`` and ``MacroManagerPanel`` are re-exported so
// ``EditorView.vue`` and the dashboard can import them by name.
// ``McodePanel`` and ``McodeManagerPanel`` are also re-exported —
// they live in the same module (same data shape, same Pinia store)
// but cover the LinuxCNC custom-M-code surface
// (``machine_config/m_codes/``).

import manifest from "./manifest.js";
import MacroPanel from "./components/MacroPanel.vue";
import MacroManagerPanel from "./components/MacroManagerPanel.vue";
import McodePanel from "./components/McodePanel.vue";
import McodeManagerPanel from "./components/McodeManagerPanel.vue";
import { useMacrosStore } from "./store.js";

export default {
  manifest,
  // The macros module renders its dashboard panel as the route
  // view (when the legacy ``/macros`` slot is opened directly).
  mainView: MacroPanel,
  onLoad(/* ctx */) {
    // Eagerly construct the store against the active Pinia
    // instance. ``loadList`` runs inside the panel's
    // ``onMounted``; the registry's hook stays a thin constructor.
    useMacrosStore();
  },
  onUnload() {
    // No timers or sockets to release; Pinia tears the store down
    // with the parent scope.
  },
  // Direct component pointer — the registry exposes this so callers
  // that need to embed the manager panel can do so without an
  // import.meta.glob (e.g. ``EditorView.vue``).
  settingsPanel: MacroManagerPanel,
};

export {
  manifest,
  MacroPanel,
  MacroManagerPanel,
  McodePanel,
  McodeManagerPanel,
};
