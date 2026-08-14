// Tools module entrypoint. The store is initialised eagerly when
// ``onLoad`` runs — Pinia's active instance is wired up before
// ``registry.boot()`` in ``main.js``. The contract forbids lazy
// stores (``.agent/STATE.md`` § 13).

import manifest from "./manifest.js";
import ToolPanel from "./components/ToolPanel.vue";
import { useToolStore } from "./toolStore.js";

export default {
  manifest,
  mainView: ToolPanel,
  onLoad(/* ctx */) {
    // Eagerly construct the store against the active Pinia
    // instance. Idempotent — calling ``useToolStore()`` twice
    // returns the same instance.
    useToolStore();
  },
  onUnload() {
    // No background work to release; Pinia tears the store down
    // with the parent scope.
  },
};

export { manifest, ToolPanel };