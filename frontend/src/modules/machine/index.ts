// Machine module entrypoint. The frontend registry imports this file
// **statically** — no ``import.meta.glob(..., { eager: false })``,
// no ``defineAsyncComponent`` — per the no-lazy-imports rule in
// ``.agent/STATE.md`` § 13.

import manifest from "./manifest";
import DroPanel from "./components/DroPanel.vue";
import JogControls from "./components/JogControls.vue";
import {servoThreadService} from "../../facades/servoThreadFacade";

export default {
  manifest,
  mainView: DroPanel,
  onLoad(/* ctx */) {
    // Open the 10 Hz ``/ws/telemetry`` WebSocket on the servo
    // thread (idempotent — see the guard inside
    // ``stores/servoThread.js``).
    servoThreadService.connect();
  },
  onUnload() {
    // Close the socket. The store teardown is idempotent —
    // ``stop()`` is a no-op when the socket is already closed.
    servoThreadService.disconnect();
  },
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