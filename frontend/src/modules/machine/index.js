// Machine module entrypoint. The frontend registry imports this file
// lazily and consumes the default export. See ``.agent/STATE.md`` § 1
// (lazy discovery), § 2 (store id), § 4 (eager store registration).

import manifest from "./manifest.js";
import DroPanel from "./components/DroPanel.vue";
import JogControls from "./components/JogControls.vue";
import { useMachineStore } from "./store.js";
import {
  registerMachineStore,
  unregisterMachineStore,
} from "../../stores/machine-compat.js";

export default {
  manifest,
  // Toggling this hook is idempotent thanks to the ``connect()``
  // guard inside the store.
  onLoad(/* ctx */) {
    // Register only once the registry has decided to mount this
    // module. Keeps direct imports of the optional store from
    // changing the shell's fallback behaviour.
    registerMachineStore(useMachineStore);
    useMachineStore().connect();
  },
  onUnload() {
    // Disconnect the WebSocket and cancel any running keep-alive
    // intervals. ``disconnect()`` is also idempotent.
    useMachineStore().disconnect();
    unregisterMachineStore(useMachineStore);
  },
  // Re-export the components so ``DashboardView`` can keep them out
  // of the initial bundle via ``defineAsyncComponent``. See
  // ``.agent/STATE.md`` § 1.
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
