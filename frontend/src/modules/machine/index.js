// Machine module entrypoint. The frontend registry imports this file
// lazily and consumes the default export. See ``.agent/STATE.md`` § 1
// (lazy discovery), § 2 (store id).

import manifest from "./manifest.js";
import DroPanel from "./components/DroPanel.vue";
import JogControls from "./components/JogControls.vue";
import { useServoThreadStore } from "../../stores/servoThread.js";

export default {
  manifest,
  onLoad(/* ctx */) {
    // Open the 10 Hz ``/ws/telemetry`` WebSocket on the servo
    // thread (idempotent — see the guard inside
    // ``stores/servoThread.js``).
    useServoThreadStore().start();
  },
  onUnload() {
    // Close the socket. The store teardown is idempotent —
    // ``stop()`` is a no-op when the socket is already closed.
    useServoThreadStore().stop();
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
};