// Tools module entrypoint. Store is lazily initialised on first
// ``useToolStore()`` call inside ``ToolPanel.vue`` — we deliberately
// skip the eager ``onLoad`` factory call because Pinia's
// ``activePinia`` isn't always wired through Vite's pre-bundle yet.
// See ``.agent/STATE.md`` § 1, § 4.

import manifest from "./manifest.js";
import ToolPanel from "./components/ToolPanel.vue";

export default {
  manifest,
  onLoad(/* ctx */) {
    // No-op. Store factory runs on first ``useToolStore()`` call.
  },
  onUnload() {
    // No background work to release; Pinia tears the store down
    // with the parent scope.
  },
};

export { manifest, ToolPanel };