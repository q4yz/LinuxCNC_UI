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
// Health body: ``linuxcnc_connected`` (the backend can read LinuxCNC's
// status buffer) and ``shutting_down``. A backend that answers but
// cannot read LinuxCNC yet, or is shutting down, counts as a failed
// probe — the machine UI must not mount against it.
//
// While not online, the always-up system service is asked for the
// session state, so the offline card can say *why* (``offlineReason``):
// stopped / starting / connecting / stopping / external (LinuxCNC was
// started outside this UI with another INI — no machine backend for
// us; Start fails with the system service's explanation) / waiting
// (LinuxCNC runs, backend not up yet) / unresponsive (that for > 20 s
// — offer Stop) / system-offline. Before, every one of these looked
// like "offline", and Start on a running session just got 409s.
//
// ``wakeMachine()`` drives the "Start machine" button on the
// offline card: it calls the system service (:8001, always up) and
// tightens the heartbeat to 1 Hz so the UI catches the exact
// moment the machine service binds its ports. A 30 s give-up guard
// resets the button so the operator is never stuck with a spinner.

import { computed, ref, watch } from "vue";

import { SystemMachineLifecycleService } from "../../generated/api";
import {
  MachineLifecycleFacade,
  type MachineSessionState,
} from "../facades/machineLifecycleFacade";
import { describeErrorOr } from "../core/error-format";
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

// LinuxCNC reported running but the machine backend unreachable this
// long → "unresponsive" (offer Stop). Shorter is a normal boot.
const UNRESPONSIVE_AFTER_MS = 20_000;

/** Why the machine UI is not available (``null`` while online / loading). */
export type OfflineReason =
  | "stopped"
  | "starting"
  | "connecting"
  | "stopping"
  | "external"
  | "waiting"
  | "unresponsive"
  | "system-offline";

// ─────────────────────────────────────────────────────────────────
// Global singleton state — created outside the function body so
// every component and the app shell share the same refs.
// ─────────────────────────────────────────────────────────────────
const isMachineOnline = ref<boolean | null>(null);
const isChecking = ref(false);
const isStarting = ref(false);
const isStopping = ref(false);

/** Last health body: backend answered, but is LinuxCNC readable / shutting down? */
const lastHealth = ref<{ linuxcncConnected: boolean; shuttingDown: boolean } | null>(null);
/** Session state from the system service (only refreshed while not online). */
const sessionState = ref<MachineSessionState | "unreachable" | null>(null);
/** Who runs the session (``external``: started outside this UI). */
const sessionOwner = ref<"ui" | "external" | null>(null);
/** INI of the running session, when the system service could read it. */
const runningIni = ref<string | null>(null);
/** Since when the session is "running" while the backend is unreachable. */
const runningUnreachableSince = ref<number | null>(null);
const now = ref(Date.now());

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
      const body = (await response.json().catch(() => ({}))) as {
        linuxcnc_connected?: unknown;
        shutting_down?: unknown;
      };
      // An older backend without the fields is treated as connected.
      const health = {
        linuxcncConnected: body.linuxcnc_connected !== false,
        shuttingDown: body.shutting_down === true,
      };
      lastHealth.value = health;
      if (health.linuxcncConnected && !health.shuttingDown) {
        consecutiveFailures = 0;
        isMachineOnline.value = true;
      } else {
        noteProbeFailure();
      }
    } else {
      // Any non-200 (e.g. 502 from the proxy) is a dead upstream.
      lastHealth.value = null;
      noteProbeFailure();
    }
  } catch {
    // Timeout or network error — same verdict as a 502.
    lastHealth.value = null;
    noteProbeFailure();
  } finally {
    isChecking.value = false;
  }
  if (isMachineOnline.value !== true) await refreshSessionState();
}

/** Ask the always-up system service what the LinuxCNC session is doing. */
async function refreshSessionState(): Promise<void> {
  now.value = Date.now();
  try {
    const status = await MachineLifecycleFacade.getStatus();
    sessionState.value = status.state ?? (status.running ? "running" : "stopped");
    sessionOwner.value = status.owner ?? null;
    runningIni.value = status.running_ini ?? null;
  } catch {
    sessionState.value = "unreachable";
    sessionOwner.value = null;
    runningIni.value = null;
  }
  const runningButUnreachable = sessionState.value === "running" && lastHealth.value === null;
  if (!runningButUnreachable) runningUnreachableSince.value = null;
  else runningUnreachableSince.value ??= Date.now();
}

const offlineReason = computed<OfflineReason | null>(() => {
  if (isMachineOnline.value !== false) return null;
  const session = sessionState.value;
  if (isStopping.value || lastHealth.value?.shuttingDown || session === "stopping") return "stopping";
  if (isStarting.value || session === "starting") return "starting";
  if (lastHealth.value && !lastHealth.value.linuxcncConnected) return "connecting";
  // Started outside this UI: there is no machine backend to wait for.
  if (session === "running" && sessionOwner.value === "external") return "external";
  if (session === "running") {
    const since = runningUnreachableSince.value;
    return since !== null && now.value - since > UNRESPONSIVE_AFTER_MS ? "unresponsive" : "waiting";
  }
  if (session === "unreachable") return "system-offline";
  return "stopped";
});

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
      // 409: LinuxCNC already runs (typically started from another
      // process with another INI) or another start/stop is in progress.
      // The system service's detail says which and what to do — show
      // it as a failure instead of silently waiting for a backend that
      // will never come.
      const reason =
        status === 409
          ? describeErrorOr(err, "LinuxCNC is already running.")
          : describeErrorOr(err, "see backend logs");
      console.error("[useMachineOnline] startMachineSession failed:", err);
      useConsoleStore().error(`Failed to start the machine: ${reason}`, {
        popup: true,
        title: "Start machine",
        lifetime: status === 409 ? null : undefined,
      });
      isStarting.value = false;
      wakeGiveUpAt = 0;
      armHeartbeat(NORMAL_INTERVAL_MS);
      void refreshSessionState();
      return;
    }

    // Fire one immediate probe so a fast boot is caught before the
    // next 1 Hz tick.
    void checkMachineOnline();
  }

  /**
   * Stop the LinuxCNC session through the system service — the way out
   * of "LinuxCNC runs but the machine backend does not respond".
   */
  async function stopMachine(): Promise<void> {
    if (isStopping.value) return;
    isStopping.value = true;
    try {
      await MachineLifecycleFacade.stopMachine();
      useConsoleStore().info("LinuxCNC stopped");
    } catch (err: unknown) {
      useConsoleStore().error(
        `Failed to stop LinuxCNC: ${err instanceof Error ? err.message : String(err)}`,
        { popup: true, title: "Stop LinuxCNC", lifetime: null },
      );
    } finally {
      isStopping.value = false;
      void checkMachineOnline();
    }
  }

  return {
    isMachineOnline,
    isChecking,
    isStarting,
    isStopping,
    offlineReason,
    runningIni,
    checkMachineOnline,
    startHeartbeat,
    stopHeartbeat,
    wakeMachine,
    stopMachine,
  };
}

export default useMachineOnline;
