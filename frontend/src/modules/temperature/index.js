// Temperature module entrypoint. The store is initialised eagerly
// when ``onLoad`` runs — Pinia's active instance is wired up before
// ``registry.boot()`` in ``main.js`` so the historic
// ``activePinia._s.has(...)`` timing trap is no longer relevant.
// See ``.agent/STATE.md`` § 13 for the no-lazy-imports rule and
// ``.agent/STATE.md`` § 4 for the eager store boot rationale.

import manifest from "./manifest.js";
import TemperaturePanel from "./components/TemperaturePanel.vue";
import TemperatureSettingsPanel from "./components/TemperatureSettingsPanel.vue";
import { useTemperatureStore } from "./store.js";

export default {
  manifest,
  // The temperature module does not contribute a top-level nav
  // entry — it lives inside the dashboard grid. ``mainView`` is the
  // panel the App shell mounts when the user navigates to a
  // temperature-flavoured route (none today, but the contract
  // forbids a null ``mainView`` so we ship the panel).
  mainView: TemperaturePanel,
  // Required by the contract — the panel must be a non-null Vue
  // component. The Settings view tolerates a placeholder for
  // modules without a panel but the registry itself rejects null.
  settingsPanel: TemperatureSettingsPanel,
  onLoad(/* ctx */) {
    // Eagerly wire the temperature store against the now-active
    // Pinia instance. ``start()`` is idempotent and a no-op when
    // the panel is never mounted.
    useTemperatureStore();
  },
  onUnload() {
    // Pinia tears the store down with the parent scope. Kept as a
    // no-op for the contract.
  },
};

export {
  manifest,
  TemperaturePanel,
  TemperatureSettingsPanel,
};
