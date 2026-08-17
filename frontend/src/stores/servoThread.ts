// Servo-thread store.
//
// LinuxCNC's runtime splits into two clocks:
//
//   * Servo thread — 10 Hz ``/ws/telemetry`` WebSocket stream carrying
//     time-critical state: position, task_state, estop, errors,
//     interpreter, current_line. This file.
//
//   * Base thread — 1 Hz ``/api/v1/base-thread/snapshot`` REST
//     round-trip bundling every slow stream (program progress,
//     temperature sensors, tool list). See ``stores/baseThread.js``.
//
// This store owns the WebSocket transport + the reactive state the
// fast clock produces. The machine MODULE
// (``modules/machine/store.js``) composes this store for telemetry
// and adds its own jog / keepalive / settings / program-lifecycle
// actions on top — keeping the transport here means the
// lifecycle of the socket is independent of any single module.
//
// Every incoming ``full_state`` / ``delta`` payload is mirrored to
// the State Facade (``stores/stateFacade.js``) so widgets that
// read the high-resolution state vocabulary do not need to know
// which clock the data came from.
//
// ───────────────────────────────────────────────────────────────────
// USAGE
// ───────────────────────────────────────────────────────────────────
//
// Boot once at app mount, then read from any consumer:
//
//   // frontend/src/App.vue (script setup, top level)
//   import { useServoThreadStore } from './stores/servoThread'
//   useServoThreadStore().start()      // idempotent — safe from
//                                      // hot-reload boundaries
//
//   // any consumer module
//   import { useServoThreadStore } from '../../stores/servoThread'
//   const servo = useServoThreadStore()
//   const { status, connectionStatus, errors } = storeToRefs(servo)
//
//   // disconnect on unmount
//   servo.stop()
//
// ───────────────────────────────────────────────────────────────────
// GOTCHAS (see ``.agent/context/LESSONS_LEARNED.md`` § 2.5)
// ───────────────────────────────────────────────────────────────────
//
// * The reconnect / socket handles are non-state properties on the
//   Pinia store instance — they start as ``undefined``. Any gate on
//   them must use a truthy check (``if (this._socket)``), not a
//   strict-null check (``if (this._socket !== null)``), or the first
//   ``start()`` call returns early and the WebSocket never opens.

import { defineStore, storeToRefs } from "pinia";
import { reactive, ref } from "vue";

import { useMachineStore as useFacadeStore } from "./stateFacade";
import { useConsoleStore } from "./console";

// Reconnect cadence — 2 s is a polite back-off. LinuxCNC drops
// the socket on E-Stop transitions and recovers quickly; faster
// retries spam the backend's WebSocket accept loop.
const RECONNECT_DELAY_MS = 2_000;

// Sensible default for the very first render before the socket
// has ever opened. Mirrors ``stateFacade.js``'s own defaults so a
// widget that destructures ``status`` from both stores sees
// consistent values.
const DEFAULT_STATUS = Object.freeze({
  task_state: 1,
  estop: 1,
  task_mode: 1,
  position: [0, 0, 0, 0, 0, 0, 0, 0, 0],
  actual_position: [0, 0, 0, 0, 0, 0, 0, 0, 0],
  relative_position: [0, 0, 0, 0, 0, 0, 0, 0, 0],
  state: 1,
  file: "",
  homed: [0, 0, 0],
  interp_state: 1,
  current_line: 0,
  total_lines: 0,
  g5x_index: 1,
});

export const useServoThreadStore = defineStore("servoThread", () => {
  // --- Reactive state ---------------------------------------------- //

  // 'disconnected' | 'connecting' | 'connected' — mirrors the
  // machine module's WebSocket lifecycle so the State Facade can
  // short-circuit to ``Offline`` when no telemetry is flowing.
  const connectionStatus = ref("disconnected");

  // Whether the backend is in the middle of a configuration
  // update (``status: "updating"``). The widget hides progress
  // during an update so the operator does not panic over a
  // frozen bar.
  const isUpdating = ref(false);

  // Full LinuxCNC stat payload. ``reactive`` (not ``ref``) so the
  // ``applyDelta`` helper can mutate individual keys without
  // losing reactivity — see the servo-thread / base-thread split
  // comment at the top of the file.
  const status = reactive({ ...DEFAULT_STATUS });

  // Bounded queue of recent LinuxCNC error-channel events. The
  // ``MachineErrorChannel`` (console) reads from this to render
  // the backlog after a reconnect / page reload.
  const errors = ref([]);

  // --- Non-reactive handles -------------------------------------- //

  let socket = null;
  let reconnectTimer = null;
  // When ``false``, ``disconnect()`` suppressed further reconnect
  // attempts. Reset to ``true`` on every explicit ``start()``.
  let shouldReconnect = true;

  // --- Helpers -------------------------------------------------- //

  const isPlainObject = (value) =>
    value !== null && typeof value === "object" && !Array.isArray(value);

  // Deep-merge ``delta`` into ``target``. LinuxCNC emits per-field
  // deltas (only the keys that changed since the last frame)
  // so a partial ``delta`` cannot blank the rest of the payload.
  const applyDelta = (target, delta) => {
    if (!isPlainObject(target) || !isPlainObject(delta)) {
      return target;
    }
    for (const key of Object.keys(delta)) {
      const deltaValue = delta[key];
      if (isPlainObject(deltaValue)) {
        if (!isPlainObject(target[key])) {
          target[key] = {};
        }
        applyDelta(target[key], deltaValue);
      } else {
        target[key] = deltaValue;
      }
    }
    return target;
  };

  // Mirror the live state into the State Facade so widgets that
  // destructure ``systemState`` / ``printProgress`` / etc. see
  // up-to-date values without importing this store directly.
  // ``useFacadeStore`` is aliased to avoid colliding with the
  // compat shim's ``useMachineStore`` (same name, different role).
  const mirrorToFacade = () => {
    useFacadeStore().updateStatus({
      connectionStatus: connectionStatus.value,
      isUpdating: isUpdating.value,
      status: { ...status },
    });
  };

  // ──────────────────────────────────────────────────────────────── //
  // Lifecycle                                                          //
  // ──────────────────────────────────────────────────────────────── //

  /**
   * Open the ``/ws/telemetry`` socket. Idempotent — calling twice
   * while a socket is ``connecting`` or ``connected`` is a no-op
   * so hot-reloads cannot stack sockets. ``disconnect()`` clears
   * ``shouldReconnect``; the next ``start()`` resets it so a
   * deliberate disconnect followed by a deliberate reconnect
   * works.
   */
  function start() {
    // Guard against double-mount. We can't rely on a strict-null
    // check on ``socket`` (see GOTCHAS § 2.5 — ``socket`` is a
    // non-state property that starts as ``undefined``).
    if (socket) return;
    shouldReconnect = true;
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    connect();
  }

  /**
   * Close the socket and suppress reconnect attempts. Safe to
   * call when no socket is open; safe to call twice.
   */
  function stop() {
    shouldReconnect = false;
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    const currentSocket = socket;
    // Clear the reference before closing so the async ``onclose``
    // handler cannot schedule a reconnect during teardown.
    socket = null;
    if (currentSocket) currentSocket.close();
    connectionStatus.value = "disconnected";
    mirrorToFacade();
  }

  /**
   * Send a JSON command over the open telemetry socket.
   *
   * The /ws/telemetry channel is now bidirectional: the backend
   * accepts ``jog_axis`` / ``jog_keepalive`` / ``jog_stop`` JSON
   * messages and dispatches them to the same ``ws_jog_*`` helpers
   * the legacy REST endpoints use. Fire-and-forget — the
   * 10 Hz ``full_state`` / ``delta`` broadcast reflects the
   * new state on the next tick, so a missing reply is fine.
   *
   * No-op with a ``console.warn`` when the socket isn't open. The
   * backend watchdog will eventually force-stop the axis if
   * keep-alives stop arriving, so a missing send is a safe
   * failure mode (matches the documented safety contract).
   *
   * @param {Record<string, any>} payload
   * @returns {boolean} true when the message was queued on the socket
   */
  function send(payload) {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      // eslint-disable-next-line no-console
      console.warn(
        "[servoThread] cannot send: socket not open",
        payload,
      );
      return false;
    }
    try {
      socket.send(JSON.stringify(payload));
      return true;
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("[servoThread] send failed:", err);
      return false;
    }
  }

  /**
   * Internal: open the socket and wire the lifecycle handlers.
   * Split out from ``start()`` so the reconnect path (set up by
   * ``onclose``) can call it without re-entering the idempotency
   * guard.
   */
  function connect() {
    if (socket) return;
    if (
      typeof window === "undefined" ||
      typeof WebSocket === "undefined"
    ) {
      connectionStatus.value = "disconnected";
      mirrorToFacade();
      return;
    }

    connectionStatus.value = "connecting";
    mirrorToFacade();

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.hostname}:8000/ws/telemetry`;
    const currentSocket = new WebSocket(wsUrl);
    socket = currentSocket;

    currentSocket.onopen = () => {
      // eslint-disable-next-line no-console
      console.log("Connected to LinuxCNC Telemetry");
      connectionStatus.value = "connected";
      // Mirror to the State Facade so its ``systemState`` flips out
      // of ``Offline`` immediately.
      mirrorToFacade();
    };

    currentSocket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);

        if (payload.type === "full_state") {
          // Replace the entire state in one shot so a delta and
          // its follow-up ``full_state`` cannot drift apart.
          const next = payload.data || {};
          for (const key of Object.keys(status)) {
            delete status[key];
          }
          Object.assign(status, next);
          mirrorToFacade();

          // Replay historical LinuxCNC errors through the global
          // console store so the operator's ``ConsolePanel`` shows
          // the backlog on reconnect / page reload. The live
          // ``error`` channel below handles new events; we dedupe
          // here so the same entry never renders twice.
          if (Array.isArray(next.errors)) {
            const liveTimes = new Set(errors.value.map((e) => e.time));
            for (const entry of next.errors) {
              if (liveTimes.has(entry.time)) continue;
              errors.value.push(entry);
              useConsoleStore().error(`LinuxCNC: ${entry.text}`, {
                title: `LinuxCNC error (kind=${entry.kind})`,
                popup: true,
              });
            }
          }
        } else if (payload.type === "delta") {
          applyDelta(status, payload.data);
          mirrorToFacade();
        } else if (payload.type === "error") {
          errors.value.push(payload.data);
          // Route through the global console store so the
          // operator's ``ConsolePanel`` renders the row and the
          // toast fires. ``popup: true`` is required because
          // ``core/console.js`` short-circuits ``_emitToast`` when
          // the flag is missing.
          useConsoleStore().error(`LinuxCNC: ${payload.data.text}`, {
            title: `LinuxCNC error (kind=${payload.data.kind})`,
            popup: true,
          });
          // eslint-disable-next-line no-console
          console.error("Machine Error:", payload.data.text);
        }
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("Failed to parse websocket message", err);
      }
    };

    currentSocket.onclose = () => {
      // Ignore a close event from a socket that was explicitly
      // replaced. Prevents stale sockets from changing the status
      // of a newer connection.
      if (socket !== currentSocket) return;

      // eslint-disable-next-line no-console
      console.warn(
        "WebSocket disconnected. Retrying in 2 seconds...",
      );
      connectionStatus.value = "disconnected";
      socket = null;
      mirrorToFacade();

      if (shouldReconnect && reconnectTimer === null) {
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null;
          connect();
        }, RECONNECT_DELAY_MS);
      }
    };

    currentSocket.onerror = (err) => {
      // eslint-disable-next-line no-console
      console.error("WebSocket error:", err);
      if (socket === currentSocket) currentSocket.close();
    };
  }

  // ──────────────────────────────────────────────────────────────── //
  // Public surface                                                    //
  // ──────────────────────────────────────────────────────────────── //

  return {
    // Reactive state.
    connectionStatus,
    isUpdating,
    status,
    errors,
    // Lifecycle.
    start,
    stop,
    // Bidirectional — send JSON commands over the open socket.
    // The backend's ``/ws/telemetry`` handler dispatches jog /
    // keepalive / stop messages to the same ``ws_jog_*`` helpers
    // the REST endpoints use, so behaviour is identical and the
    // WS path is the canonical transport going forward.
    send,
  };
});

/**
 * Convenience wrapper around ``storeToRefs`` so callers can
 * destructure the reactive state without losing reactivity.
 *
 * @returns {{store: import('pinia').Store, ...import('vue').ToRefs<...>}}
 */
export function useServoThreadRefs() {
  const store = useServoThreadStore();
  return { store, ...storeToRefs(store) };
}

export default useServoThreadStore;