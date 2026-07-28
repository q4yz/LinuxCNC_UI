// Machineconfig module entrypoint. ``onLoad`` triggers the initial
// state load; ``onUnload`` is a no-op because the store owns no
// timers or sockets. The UI lives directly in the legacy
// ``ConfigView`` so this module no longer exposes a standalone
// component shell. See ``.agent/STATE.md`` § 1, § 2.

import manifest from "./manifest.js";
import { useMachineConfigStore } from "./store.js";

export default {
  manifest,
  onLoad(/* ctx */) {
    // Fire and forget; components show loading skeletons until
    // the data arrives. ``loadAll`` logs the error to the console
    // store rather than throwing so a backend hiccup is recoverable.
    const store = useMachineConfigStore();
    store.loadAll();
  },
  onUnload() {
    // No background work to release.
  },
};

export {
  manifest,
  useMachineConfigStore,
};