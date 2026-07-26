// Machineconfig module entrypoint.
//
// The frontend registry
// (``frontend/src/core/modules/registry.js``) imports this file via the
// lazy ``import.meta.glob('../../modules/*/index.js', { eager: false })`` and
// consumes the default export.
//
// ``onLoad`` triggers the initial state load (compilers, profiles tree,
// staged / active listings). ``onUnload`` is a no-op because the store
// does not own timers or sockets.
//
// The store id is namespaced under the ``module_`` prefix per
// ``MODULE_SYSTEM_ROADMAP.md`` § 12 Gotcha #2 (see
// ``frontend/store-id-regex`` check script) so it never collides
// with the legacy top-level Pinia store ids.
//
// References:
//   * ``.agent/contracts/frontend-module.md`` § 1, § 5.

import manifest from "./manifest.js";
import { useMachineConfigStore } from "./store.js";
import MachineConfigView from "./components/MachineConfigView.vue";

export default {
  manifest,
  onLoad(/* ctx */) {
    // Initial state load — fire and forget; the components show
    // loading skeletons until the data arrives. We tolerate the
    // backend not being reachable yet because ``loadAll`` logs the
    // error to the console store rather than throwing.
    const store = useMachineConfigStore();
    store.loadAll();
  },
  onUnload() {
    // No background work to release; the store has no timers or sockets.
  },
  components: {
    MachineConfigView,
  },
};

export {
  manifest,
  MachineConfigView,
  useMachineConfigStore,
};