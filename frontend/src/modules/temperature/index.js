// Temperature module entrypoint. The store is lazily initialised on
// first ``useTemperatureStore()`` call inside ``TemperaturePanel.vue``
// (rather than from ``onLoad``) because the timing of
// ``app.use(pinia)`` relative to module boot is fragile, and a user
// who only opens the Settings tab never needs the polling loop. See
// ``.agent/STATE.md`` § 1 (lazy discovery), § 2 (store id).

import manifest from "./manifest.js";
import TemperaturePanel from "./components/TemperaturePanel.vue";
import TemperatureSettingsPanel from "./components/TemperatureSettingsPanel.vue";

export default {
  manifest,
  // Sidebar entry is not contributed — temperature lives inside the
  // dashboard grid, not as a top-level nav item.
  onLoad(/* ctx */) {
    // No-op. Store factory runs on first ``useTemperatureStore()``
    // call. See the long-form comment above.
  },
  onUnload() {
    // Pinia tears the store down with the parent scope. Kept as a
    // no-op for the contract.
  },
  settingsPanel: TemperatureSettingsPanel,
};

export {
  manifest,
  TemperaturePanel,
  TemperatureSettingsPanel,
};
