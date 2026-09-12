// Base-thread snapshot store.
//
// Mirrors the LinuxCNC runtime split: the 10 Hz `/ws/telemetry`
// stream is the "servo thread" (time-critical position / state /
// errors), and this store is the "base thread" — a single 1 Hz
// REST round-trip that bundles every slow stream the dashboard
// cares about.
//
// Lifecycle is owned by the app shell: ``App.vue`` starts/stops
// the poll (and the telemetry WebSocket) based on the global
// machine-online heartbeat in ``composables/useMachineOnline.ts``.
// When the machine backend is down there is deliberately NO poll
// running — no 1 Hz 502 spam, no hanging fetches, no local
// watchdog needed. The old pending-snapshot watchdog / "connection
// stuck" modal was removed in favour of that global gate.

import { defineStore } from "pinia";
import { ref, shallowRef, computed } from "vue";

import { BaseThreadService } from "../facades/baseThreadFacade";

// Entity imports for state typing and re-exporting
import { ReadingSet } from "../entities/temperature/ReadingSet";
import { ToolList } from "../entities/tools/ToolList";
import { ProgramProgress } from "../entities/progress/ProgramProgress";
import { AxisState } from "../entities/axis/AxisState";
import { HeaterReading } from "../entities/temperature/HeaterReading";
import { SensorReading } from "../entities/temperature/SensorReading";
import { SpindleDigital as SpindleState } from "../entities/tools/SpindleDigital";
import { Extruder } from "../entities/tools/Extruder";

// 1 Hz is the documented contract.
const POLL_INTERVAL_MS = 1_000;

export const useBaseThreadStore = defineStore("baseThread", () => {
  // ─────────────────────────────────────────────────────────────────
  // STATE
  // ─────────────────────────────────────────────────────────────────

  // Typed entity surface (shallowRef is massive for performance here,
  // as it prevents deep proxying of class instances every 1 Hz)
  const progress = shallowRef<ProgramProgress>(new ProgramProgress());
  const readings = shallowRef<ReadingSet>(new ReadingSet());
  const toolList = shallowRef<ToolList>(new ToolList([]));
  const axes = shallowRef<Record<string, AxisState>>({});

  // Legacy wire shape (kept for migration window)
  const sensors = ref<Record<string, any>>({});
  const tools = ref<Record<string, any>[]>([]);

  const timestamp = ref<string | null>(null);

  type ConnectionStatus = "disconnected" | "connecting" | "connected" | "error";
  const connectionStatus = ref<ConnectionStatus>("disconnected");

  // Non-reactive internals. This fixes the old gotcha: since it's a local
  // variable and not in a `state: () => ({})` block, Vue won't wrap it in a proxy.
  let pollHandle: ReturnType<typeof setInterval> | null = null;

  // `axes` is entirely static — every field the backend's own
  // AxisMapper exposes (id, jointNumbers, minLimit, maxLimit) is
  // baked into hardware.json at machine-config compile time and
  // cached by the backend's AxisService singleton for the life of
  // the machine session. Fetched once via the STATIC response tier
  // and never touched again by the 1 Hz `refresh()` below, so its
  // reference — and therefore every computed/watch downstream of it
  // (NgcCoordinateSystemViewer's axis-limit grid rebuild chief among
  // them) — stops changing after this one assignment instead of
  // getting a new (but identically-valued) object every single tick.
  let staticAxesLoaded = false;
  let staticAxesLoadPromise: Promise<void> | null = null;

  // ─────────────────────────────────────────────────────────────────
  // GETTERS
  // ─────────────────────────────────────────────────────────────────

  /** Convenience getter for components that only need the bar fraction. */
  const progressFraction = computed(() => {
    const fraction = progress.value.fraction;
    if (!Number.isFinite(fraction)) return 0;
    return fraction;
  });

  // ─────────────────────────────────────────────────────────────────
  // ACTIONS
  // ─────────────────────────────────────────────────────────────────

  /**
   * Pull the latest snapshot from the backend and write every
   * field into the store. Best-effort: a failed tick leaves the
   * previous values intact so the operator keeps seeing the last
   * known state.
   */
  async function refresh(): Promise<void> {
    try {
      // The BaseThreadService handles all data extraction and mappers now
      const snapshot = await BaseThreadService.fetchSnapshot();

      // Entity Surface. ``axes`` is deliberately NOT reassigned here
      // — it's wholly static data, sourced once by fetchStaticAxes()
      // below, not by this 1 Hz poll. See the comment by
      // `staticAxesLoaded` above.
      progress.value = snapshot.progress;
      readings.value = snapshot.readings;
      toolList.value = snapshot.toolList;

      timestamp.value = snapshot.timestamp;
      connectionStatus.value = "connected";
    } catch (err: unknown) {
      // Loud logging — silent swallows have masked two regressions already.
      console.error("[baseThread] refresh failed:", err);
      connectionStatus.value = "error";
    }
  }

  /**
   * Fetch the STATIC response tier exactly once per session and use
   * it as the sole, permanent source for ``axes``. Idempotent (a
   * shared in-flight promise, same pattern as
   * `stores/machine.ts`'s `refreshSettings()`) so re-entering while
   * a fetch is already running never fires a second request.
   */
  async function fetchStaticAxes(): Promise<void> {
    if (staticAxesLoaded) return;
    if (staticAxesLoadPromise) return staticAxesLoadPromise;
    staticAxesLoadPromise = (async () => {
      try {
        const snapshot = await BaseThreadService.fetchStatic();
        axes.value = snapshot.axes;
      } catch (err: unknown) {
        console.error("[baseThread] fetchStaticAxes failed:", err);
      } finally {
        staticAxesLoaded = true;
      }
    })();
    return staticAxesLoadPromise;
  }

  /**
   * Arm the 1 Hz snapshot poll. Fires immediately so the operator
   * sees populated data on the first frame after the machine comes
   * online, then settles into the 1 Hz cadence.
   */
  function armPoll(): void {
    if (pollHandle) return;
    connectionStatus.value = "connecting";

    void refresh();
    void fetchStaticAxes();

    pollHandle = setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
  }

  /**
   * Start the 1 Hz polling loop. Idempotent: re-entering while
   * running is a no-op, so hot-reloads and double-mounts do not
   * stack intervals.
   */
  function start(): void {
    armPoll();
  }

  /**
   * Stop the polling loop. Safe to call when the loop is not
   * running; safe to call twice. Called by ``App.vue`` the moment
   * the machine-online heartbeat reports the backend down so the
   * dashboard stops generating failing requests.
   */
  function stop(): void {
    if (pollHandle) {
      clearInterval(pollHandle);
      pollHandle = null;
    }
    connectionStatus.value = "disconnected";
  }

  // ─────────────────────────────────────────────────────────────────
  // PUBLIC API
  // ─────────────────────────────────────────────────────────────────
  return {
    // State
    progress,
    readings,
    toolList,
    axes,
    sensors,
    tools,
    timestamp,
    connectionStatus,
    // Getters
    progressFraction,
    // Actions
    refresh,
    start,
    stop,
  };
});

export default useBaseThreadStore;

export {
  AxisState,
  HeaterReading,
  SensorReading,
  ReadingSet,
  SpindleState as SpindleDigital, // Exported as SpindleDigital to not break legacy imports
  Extruder,
  ToolList,
  ProgramProgress,
};
