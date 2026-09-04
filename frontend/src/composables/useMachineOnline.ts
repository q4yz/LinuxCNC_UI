// Global machine-online heartbeat.
//
// The deployment splits the backend in two: the *system* service
// (:8001, always up — configs, macros, machine start/stop) and the
// *machine* service (:8000, telemetry + motion — can be down while
// the system side keeps running). Every machine-level widget, the
// 1 Hz snapshot poll and the telemetry WebSocket talk to :8000;
// when that port is dead the browser used to spray 502s, hang
// MJPEG streams and pop a false "connection stuck" modal.
//
// This composable is the single source of truth for "is the
// machine side reachable":
//
//   * ``isMachineOnline === null``  → LOADING (boot; no UI mounted)
//   * ``isMachineOnline === false`` → machine offline (gate UI)
//   * ``isMachineOnline === true``  → machine online
//
// ``null`` is deliberately a *loading* state, never treated as
// online — treating it as online would mount the camera, open the
// WS and start 1 Hz polls against a possibly-dead port for the
// first seconds ("reverse flash" of 502 spam).
//
// Probe contract: ``GET /api/v1/health`` on the machine service
// with a 2 s ``AbortSignal.timeout`` — a hang and a 502 are both
// failures. Flapping is guarded by hysteresis: after being online
// it takes 2 consecutive failures to go offline (a single blip is
// ignored); from the boot (null) state a single failure is enough
// because nothing is mounted yet and the offline card should show
// immediately. One success always restores online.
//
// ``wakeMachine()`` drives the "Start machine" button on the
// offline card: it calls the system service (:8001, always up) and
// tightens the heartbeat to 1 Hz so the UI catches the exact
// moment the machine service binds its ports. A 30 s give-up guard
// resets the button so the operator is never stuck with a spinner.

import { ref, watch } from "vue";

import { SystemMachineLifecycleService } from "../../generated/api";
import { useConsoleStore } from "../stores/console";

// Normal heartbeat cadence.
const NORMAL_INTERVAL_MS = 3_000;

// Cadence while waiting for a ``wakeMachine()`` boot to land so the
// online flip is noticed within ~1 s of the ports binding.
const WAKE_INTERVAL_MS = 1_000;

// Probe timeout — a hung request must not stall the heartbeat.
const PROBE_TIMEOUT_MS = 2_000;

// Consecutive failures required to flip online → offline. From the
// boot (null) state ONE failure is enough (nothing is mounted, the
// offline card is the honest answer immediately).
const REQUIRED_FAILURES = 2;

// If a ``wakeMachine()`` boot has not produced a healthy machine
// service after this long, stop the spinner and warn.
const WAKE_GIVE_UP_MS = 30_000;

// ─────────────────────────────────────────────────────────────────
// Global singleton state — created outside the function body so
// every component and the app shell share the same refs.
// ─────────────────────────────────────────────────────────────────
const isMachineOnline = ref<boolean | null>(null);
const isChecking = ref(false);
const isStarting = ref(false);

let heartbeatHandle: number | null = null;
let currentIntervalMs = NORMAL_INTERVAL_MS;
let consecutiveFailures = 0;
let wakeGiveUpAt = 0;

function noteProbeFailure(): void {
  consecutiveFailures += 1;
  // Boot (null): first failure settles the loading state to
  // offline at once. Online: require the hysteresis count so a
  // single dropped probe does not flap the whole UI.
  if (
    isMachineOnline.value === null ||
    consecutiveFailures >= REQUIRED_FAILURES
  ) {
    isMachineOnline.value = false;
  }
}

async function checkMachineOnline(): Promise<void> {
  if (isChecking.value) return;
  isChecking.value = true;
  try {
    const response = await fetch("/api/v1/health", {
      method: "GET",
      cache: "no-store",
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    });
    if (response.ok) {
      consecutiveFailures = 0;
      isMachineOnline.value = true;
    } else {
      // Any non-200 (e.g. 502 from the proxy) is a dead upstream.
      noteProbeFailure();
    }
  } catch {
    // Timeout or network error — same verdict as a 502.
    noteProbeFailure();
  } finally {
    isChecking.value = false;
  }
}

function armHeartbeat(intervalMs: number): void {
  currentIntervalMs = intervalMs;
  if (heartbeatHandle !== null) window.clearInterval(heartbeatHandle);
  heartbeatHandle = window.setInterval(() => {
    // Give-up guard: a wake that never lands must release the
    // Start button and restore the normal cadence.
    if (wakeGiveUpAt > 0 && Date.now() > wakeGiveUpAt) {
      wakeGiveUpAt = 0;
      isStarting.value = false;
      armHeartbeat(NORMAL_INTERVAL_MS);
      useConsoleStore().warning(
        "Machine did not come online within 30 s of the start request",
      );
      return;
    }
    void checkMachineOnline();
  }, currentIntervalMs);
}

// When a wake succeeds, release the Start button and relax the
// heartbeat back to the normal cadence. Module-scope watch on
// singleton state — lives for the app's lifetime by design.
watch(isMachineOnline, (next) => {
  if (next === true && isStarting.value) {
    isStarting.value = false;
    wakeGiveUpAt = 0;
    armHeartbeat(NORMAL_INTERVAL_MS);
    useConsoleStore().success("Machine is online");
  }
});

export function useMachineOnline() {
  /**
   * Start the heartbeat: one immediate probe, then the periodic
   * cadence. Idempotent — the app shell may call it from every
   * mount without stacking intervals.
   */
  function startHeartbeat(): void {
    if (heartbeatHandle !== null) return;
    void checkMachineOnline();
    armHeartbeat(NORMAL_INTERVAL_MS);
  }

  function stopHeartbeat(): void {
    if (heartbeatHandle !== null) {
      window.clearInterval(heartbeatHandle);
      heartbeatHandle = null;
    }
  }

  /**
   * Operator pressed "Start machine" on the offline card. Delegates
   * the actual spawn to the always-up system service (:8001); a
   * 409 (already running) is fine — the machine service may just be
   * slow to bind. Any other failure releases the button and warns.
   */
  async function wakeMachine(): Promise<void> {
    if (isStarting.value) return;
    isStarting.value = true;
    wakeGiveUpAt = Date.now() + WAKE_GIVE_UP_MS;

    // Poll fast so the online flip lands within ~1 s of boot.
    armHeartbeat(WAKE_INTERVAL_MS);

    try {
      await SystemMachineLifecycleService.startMachineSession();
    } catch (err: unknown) {
      const status = (err as { status?: unknown } | null)?.status;
      if (status === 409) {
        // Already running — keep the fast poll and let the health
        // probe decide when the service is actually reachable.
        return;
      }
      console.error("[useMachineOnline] startMachineSession failed:", err);
      useConsoleStore().error(
        "Failed to start the machine (see backend logs)",
      );
      isStarting.value = false;
      wakeGiveUpAt = 0;
      armHeartbeat(NORMAL_INTERVAL_MS);
      return;
    }

    // Fire one immediate probe so a fast boot is caught before the
    // next 1 Hz tick.
    void checkMachineOnline();
  }

  return {
    isMachineOnline,
    isChecking,
    isStarting,
    checkMachineOnline,
    startHeartbeat,
    stopHeartbeat,
    wakeMachine,
  };
}

export default useMachineOnline;
