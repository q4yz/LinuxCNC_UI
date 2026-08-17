// Machineconfig module entrypoint. ``onLoad`` keeps the legacy
// fire-and-forget ``loadAll`` so the dashboard warm-starts before the
// operator lands on Machine Config; ``onUnload`` is a no-op because
// the store owns no timers or sockets.
//
// ``mainView`` is the top-level Vue component the registry routes
// ``/machineconfig`` to. ``App.vue`` reads ``mainView`` synchronously
// from the record so a sidebar click on "Machine Config" lands on
// the full panel grid. The module is a hard dependency: components
// are imported **statically** (no ``defineAsyncComponent``), per the
// no-lazy-imports rule documented in ``.agent/STATE.md`` § 13.

import manifest from "./manifest";
import { useMachineConfigStore } from "./store";
import MachineConfigView from './components/MachineConfigView.vue';

export default {
  manifest,
  sidebar: manifest.sidebar,
  mainView: MachineConfigView,
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
  MachineConfigView,
};
