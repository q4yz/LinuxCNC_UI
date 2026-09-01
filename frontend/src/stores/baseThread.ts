// Base-thread snapshot store.
//
// Mirrors the LinuxCNC runtime split: the 10 Hz `/ws/telemetry`
// stream is the "servo thread" (time-critical position / state /
// errors), and this store is the "base thread" — a single 1 Hz
// REST round-trip that bundles every slow stream the dashboard
// cares about.
//
// Pending-snapshot watchdog
// -------------------------
// ``connectionStatus`` only flips to ``"error"`` when ``fetch()``
// throws or rejects. A network hang (e.g. the browser can't allocate
// a connection slot, or Nginx/uvicorn is stuck) leaves the fetch
// pending forever with no user-visible signal — the dashboard
// stays "connecting" silently. The watchdog observes wall-clock
// timing against the last successful snapshot: when the gap
// exceeds ``PENDING_TIMEOUT_MS`` (6 s) the ``PendingSnapshotDialog``
// mounted in ``App.vue`` pops a modal with a refresh button.
//
// Detection runs independently of the fetch path (the watchdog
// ticks every second whether ``refresh()`` is awaiting or not) so
// it surfaces the "stuck" state, not just hard failures.

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

// Operator-visible threshold for the "connection appears stuck"
// dialog. Exported so the structural test can pin it; tune via the
// dialog's wording rather than this constant if the user-facing copy
// needs to change.
const PENDING_TIMEOUT_MS = 6_000;

// After the operator hits "Dismiss", suppress re-arming the
// pending dialog for this many milliseconds (unless a fresh
// "Refresh" explicitly re-arms the watchdog).
const PENDING_DISMISS_COOLDOWN_MS = 60_000;

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

  // Pending-snapshot watchdog state.
  //
  // ``lastSuccessAt`` is the wall-clock millisecond timestamp of the
  // most recent successful ``refresh()``. ``null`` until the first
  // good snapshot lands. ``currentAttemptStartedAt`` is set when a
  // fetch begins so a user-driven "Refresh" can re-arm the
  // watchdog (without it, a still-hanging fetch would not re-fire
  // the dialog even if the operator dismissed it).
  //
  // ``pendingSince`` flips to the moment we first observed an
  // unhealthy gap exceeding ``PENDING_TIMEOUT_MS`` and stays
  // sticky until the next success — the dialog and badge both
  // key off this single boolean.
  //
  // ``pendingDismissedUntil`` suppresses re-arming for a cooldown
  // so a dismissed dialog stays quiet (unless the user explicitly
  // hits Refresh).
  const lastSuccessAt = ref<number | null>(null);
  const currentAttemptStartedAt = ref<number | null>(null);
  const pendingSince = ref<number | null>(null);
  const pendingDismissedUntil = ref<number>(0);
  const secondsSinceLastSnapshot = ref<number>(0);

  // Non-reactive internals. This fixes the old gotcha: since it's a local
  // variable and not in a `state: () => ({})` block, Vue won't wrap it in a proxy.
  let pollHandle: ReturnType<typeof setInterval> | null = null;
  let watchdogHandle: ReturnType<typeof setInterval> | null = null;
  let startedAt = 0;

  // ─────────────────────────────────────────────────────────────────
  // GETTERS
  // ─────────────────────────────────────────────────────────────────

  /** Convenience getter for components that only need the bar fraction. */
  const progressFraction = computed(() => {
    const fraction = progress.value.fraction;
    if (!Number.isFinite(fraction)) return 0;
    return fraction;
  });

  /**
   * True while the dashboard hasn't received a snapshot within
   * ``PENDING_TIMEOUT_MS``. Bound to the "connection stuck" dialog
   * (the badge in the EStop header reads ``secondsSinceLastSnapshot``
   * directly).
   */
  const isPending = computed<boolean>(() => pendingSince.value !== null);

  // ─────────────────────────────────────────────────────────────────
  // WATCHDOG
  // ─────────────────────────────────────────────────────────────────

  /**
   * Per-second tick that drives the "seconds since last snapshot"
   * counter and decides whether to flip ``pendingSince``. Runs
   * independently of the fetch path so a hung ``refresh()`` still
   * surfaces — the tick does not call ``refresh()`` itself.
   */
  function evaluatePending(): void {
    const now = Date.now();
    const referenceAt = lastSuccessAt.value ?? startedAt;
    if (referenceAt === 0) {
      secondsSinceLastSnapshot.value = 0;
      return;
    }
    const elapsedMs = now - referenceAt;
    const elapsedSec = Math.max(0, Math.round(elapsedMs / 1000));
    secondsSinceLastSnapshot.value = elapsedSec;

    // While a fresh refresh is in flight, treat the reference as
    // "just now" so a brief stall doesn't pop the dialog.
    const inFlight = currentAttemptStartedAt.value !== null
      && currentAttemptStartedAt.value > lastSuccessAt.value;
    const effectiveMs = inFlight ? 0 : elapsedMs;

    if (effectiveMs < PENDING_TIMEOUT_MS) {
      // Snapshot recovered — clear sticky pending state (the
      // dialog auto-closes by v-if'ing on the cleared value).
      if (pendingSince.value !== null) pendingSince.value = null;
      return;
    }

    if (
      pendingSince.value === null &&
      pendingDismissedUntil.value <= now
    ) {
      pendingSince.value = now;
    }
  }

  function dismissPendingPrompt(): void {
    pendingDismissedUntil.value = Date.now() + PENDING_DISMISS_COOLDOWN_MS;
  }

  /**
   * Force-re-arm the watchdog (e.g. after the operator hits
   * "Refresh" in the dialog). Resets the in-flight reference so
   * the next 6 s gap is measured from this very moment.
   */
  function markSnapshotPending(): void {
    currentAttemptStartedAt.value = Date.now();
    pendingDismissedUntil.value = 0;
    pendingSince.value = null;
  }

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
    currentAttemptStartedAt.value = Date.now();
    try {
      // The BaseThreadService handles all data extraction and mappers now
      const snapshot = await BaseThreadService.fetchSnapshot();

      // Entity Surface
      progress.value = snapshot.progress;
      readings.value = snapshot.readings;
      toolList.value = snapshot.toolList;
      axes.value = snapshot.axes;

      timestamp.value = snapshot.timestamp;
      connectionStatus.value = "connected";
      lastSuccessAt.value = Date.now();
      pendingSince.value = null;
      secondsSinceLastSnapshot.value = 0;
    } catch (err: unknown) {
      // Loud logging — silent swallows have masked two regressions already.
      console.error("[baseThread] refresh failed:", err);
      connectionStatus.value = "error";
    } finally {
      currentAttemptStartedAt.value = null;
    }
  }

  /**
   * Start the 1 Hz polling loop. Idempotent: re-entering while
   * a loop is already running is a no-op so hot-reloads and
   * double-mounts do not stack intervals.
   */
  function start(): void {
    if (pollHandle) return;

    connectionStatus.value = "connecting";
    startedAt = Date.now();
    lastSuccessAt.value = null;
    pendingSince.value = null;
    pendingDismissedUntil.value = 0;
    secondsSinceLastSnapshot.value = 0;

    // Fire immediately so the operator sees populated data on
    // the first frame after mount, then settle into the 1 Hz cadence.
    void refresh();

    pollHandle = setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);

    // Independent 1 Hz watchdog — runs whether or not refresh() is
    // currently awaiting so a hung fetch still surfaces the
    // "stuck" dialog after 6 s.
    watchdogHandle = setInterval(evaluatePending, POLL_INTERVAL_MS);
  }

  /**
   * Stop the polling loop. Safe to call when the loop is not
   * running; safe to call twice. Exposed for tests and for the
   * future `onScopeDispose` hook on the store's host module.
   */
  function stop(): void {
    if (pollHandle) {
      clearInterval(pollHandle);
      pollHandle = null;
    }
    if (watchdogHandle) {
      clearInterval(watchdogHandle);
      watchdogHandle = null;
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
    pendingSince,
    secondsSinceLastSnapshot,
    // Getters
    progressFraction,
    isPending,
    // Actions
    refresh,
    start,
    stop,
    dismissPendingPrompt,
    markSnapshotPending,
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
  PENDING_TIMEOUT_MS,
};
