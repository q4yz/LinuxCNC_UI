// Machine module entrypoint. The frontend registry imports this file
// lazily and consumes the default export. See ``.agent/STATE.md`` § 1
// (lazy discovery), § 2 (store id), § 4 (eager store registration).

import manifest from "./manifest.js";
import DroPanel from "./components/DroPanel.vue";
import JogControls from "./components/JogControls.vue";
import { useMachineStore } from "./store.js";
import { useServoThreadStore } from "../../stores/servoThread.js";
import {
  registerMachineStore,
  unregisterMachineStore,
} from "../../stores/machineStoreShim.js";

export default {
  manifest,
  onLoad(/* ctx */) {
    // Register this module's store with the legacy compat shim
    // so pre-migration components that call ``useMachineStore()``
    // resolve to the module store. Then open the 10 Hz WebSocket
    // on the servo thread (idempotent — see the guard inside
    // ``stores/servoThread.js``).
    registerMachineStore(useMachineStore);
    useServoThreadStore().start();
  },
  onUnload() {
    // Close the socket and clear the shim's registration. The
    // store teardown is idempotent — ``stop()`` is a no-op when
    // the socket is already closed.
    useServoThreadStore().stop();
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
