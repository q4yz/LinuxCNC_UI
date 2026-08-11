// Machineconfig module entrypoint. ``onLoad`` keeps the legacy
// fire-and-forget ``loadAll`` so the dashboard warm-starts before the
// operator lands on Machine Config; ``onUnload`` is a no-op because
// the store owns no timers or sockets.
//
// ``mainView`` is the new top-level Vue component the registry routes
// ``/machineconfig`` to; it replaces the dashboard surface that used
// to live in ``EditorView.vue``'s ``v-else`` branch. ``App.vue`` reads
// ``mainView`` synchronously from the record so a sidebar click on
// "Machine Config" lands on the full panel grid instead of the empty
// ``/config`` route. See ``.agent/STATE.md`` § 9.

import { defineAsyncComponent } from 'vue'

import manifest from "./manifest.js";
import { useMachineConfigStore } from "./store.js";

const MachineConfigView = defineAsyncComponent(
  () => import('./components/MachineConfigView.vue')
);

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
