// Machine module entrypoint.
//
// The frontend registry (``frontend/src/core/modules/registry.js``)
// imports this file via the lazy ``import.meta.glob('../../modules/*/index.js', { eager: false })``
// and consumes the default export.
//
// ``onLoad`` triggers the machine module's WebSocket subscription
// (``useMachineStore().connect()``); ``onUnload`` tears it back
// down. The store factory itself runs lazily on first call — we do
// not force a Pinia store creation here because the timing of
// ``app.use(pinia)`` relative to module ``onLoad`` is fragile (see
// the same comment in ``temperature/index.js``).
//
// The store id is namespaced under the ``module_`` prefix per
// ``MODULE_SYSTEM_ROADMAP.md`` § 12 Gotcha #2 (see
// ``frontend/store-id-regex`` check script) so it never collides
// with the legacy top-level Pinia store id that consumers migrated
// from ``useMachineStore`` still import via the legacy shim.
//
// References:
//   * ``.agent/contracts/frontend-module.md`` § 1, § 5.
//   * ``MODULE_SYSTEM_ROADMAP.md`` § 12 Implementation Gotchas.

import manifest from "./manifest.js";
import DroPanel from "./components/DroPanel.vue";
import JogControls from "./components/JogControls.vue";
import { useMachineStore } from "./store.js";

export default {
  manifest,
  // The machine module owns the WebSocket subscription.  Toggling
  // this hook is idempotent thanks to the ``connect()`` guard in
  // the store (``if (this.connectionStatus === 'connected' || ...``).
  onLoad(/* ctx */) {
    useMachineStore().connect();
  },
  onUnload() {
    // Disconnect the WebSocket and cancel any running keep-alive
    // intervals.  The store's ``disconnect()`` is also idempotent.
    useMachineStore().disconnect();
  },
  // Re-export the components so callers (notably ``DashboardView``)
  // can use ``defineAsyncComponent`` + ``import.meta.glob`` to keep
  // the machine chunk out of the initial bundle (Gotcha #1).  See
  // the dashboard view for the exact import path used.
  components: {
    DroPanel,
    JogControls,
  },
};

export {
  manifest,
  DroPanel,
  JogControls,
  useMachineStore,
};
