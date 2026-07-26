// Machine module Pinia store.
//
// Replaces the bulk of the legacy monolithic ``stores/machine.js``
// that owned the WebSocket client, the delta-merge logic, and every
// machine-related action in one place.  The module-scoped store
// owns:
//
//   * ``connectionStatus`` / ``socket`` — the WebSocket
//     subscription to ``/ws/telemetry`` plus the auto-reconnect
//     loop.
//   * ``status`` — the reactive full-state object the DRO / G-code
//     viewer / debug panel read from.
//   * ``errors`` — the rolling list of telemetry-reported errors.
//   * ``jogIntervals`` — per-axis keep-alive interval handles.
//
// The store id MUST be ``module_machine`` per
// ``frontend-module.md`` § 5 (the lint script
// ``scripts/check-store-ids.mjs`` enforces this; CI fails the build
// for any other id).
//
// The temperature fields are intentionally not stored here; they are
// owned by the temperature module. The machine store republishes
// telemetry on the event bus so that module can ingest updates without
// taking ownership of the WebSocket transport.

import { defineStore, storeToRefs } from "pinia";
import { computed, reactive, ref } from "vue";

import manifest from "./manifest.js";
import { generateSetOffset } from "../../config/gcodes.js";
import { ModulesMachineService } from "../../../generated/api/services/ModulesMachineService";
import { useConsoleStore } from "../../stores/console.js";
import { createModuleSettings } from "../../core/modules/settings.js";
import { eventBus } from "../../core/modules/event-bus.js";

// Axis index → letter mapping (matches ``gcodes.js`` conventions).
const AXIS_NAMES = ["X", "Y", "Z"];

// Sentinel accepted by the backend ``/home`` endpoint to home all axes.
const HOME_ALL = -1;
const DEFAULT_JOG_VELOCITY = 500;
const DEFAULT_KEEPALIVE_INTERVAL_MS = 250;

// Bus topic published by the machine store so the temperature module
// (or any other listener) can ingest sensor updates without the
// machine store owning the data.
const STATE_TEMPERATURES_TOPIC = "state.temperatures";
const machineSettings = createModuleSettings(manifest.id);

// Pinia store id — see Gotcha #2. Built from the manifest id with
// the required ``module_`` prefix so it never collides with the
// legacy top-level stores (``machine``, ``console``).
const STORE_ID = `module_${manifest.id}`;


const isPlainObject = (value) =>
  value !== null && typeof value === "object" && !Array.isArray(value);

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


export const useMachineStore = defineStore(STORE_ID, () => {
  // ----------------------------------------------------------------- //
  // Reactive state                                                     //
  // ----------------------------------------------------------------- //

  const connectionStatus = ref("disconnected");
  // 'disconnected' | 'connecting' | 'connected'
  const status = reactive({
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
    g5x_index: 1,
  });
  const errors = ref([]);
  const jogIntervals = reactive({});
  const defaultJogVelocity = ref(DEFAULT_JOG_VELOCITY);
  const keepaliveIntervalMs = ref(DEFAULT_KEEPALIVE_INTERVAL_MS);
  const isUpdating = ref(false);

  // ----------------------------------------------------------------- //
  // Derived values (formerly getters in the options-API store)         //
  // ----------------------------------------------------------------- //

  const droX = computed(() => (status.relative_position[0] || 0).toFixed(3));
  const droY = computed(() => (status.relative_position[1] || 0).toFixed(3));
  const droZ = computed(() => (status.relative_position[2] || 0).toFixed(3));

  const isEstop = computed(() => status.estop === 1);
  const isMachineOn = computed(() => status.task_state === 4);

  const machineStateText = computed(() => {
    if (status.estop === 1) return "ESTOP";
    if (status.task_state === 3) return "OFF";
    if (status.task_state === 4) return "ON";
    return "READY";
  });

  // ----------------------------------------------------------------- //
  // Non-reactive handles                                               //
  // ----------------------------------------------------------------- //

  let socket = null;
  let reconnectTimer = null;
  let shouldReconnect = true;
  let settingsLoaded = false;

  // ----------------------------------------------------------------- //
  // Module settings                                                    //
  // ----------------------------------------------------------------- //

  async function refreshSettings() {
    try {
      const settings = await machineSettings.readAll();
      if (!settings || typeof settings !== "object") {
        settingsLoaded = true;
        return;
      }

      const velocity = Number(settings.default_jog_velocity);
      if (Number.isFinite(velocity) && velocity >= 1) {
        defaultJogVelocity.value = velocity;
      }

      const interval = Number(settings.keepalive_interval_ms);
      if (Number.isFinite(interval) && interval >= 50 && interval <= 2000) {
        keepaliveIntervalMs.value = interval;
      }
      settingsLoaded = true;
    } catch (err) {
      // Settings are optional while the machine module is disabled or
      // during the first frontend render. Keep safe historical defaults.
      settingsLoaded = true;
      // eslint-disable-next-line no-console
      console.warn("Machine settings unavailable; using defaults", err);
    }
  }

  // ----------------------------------------------------------------- //
  // WebSocket transport                                                //
  // ----------------------------------------------------------------- //

  function connect() {
    if (
      connectionStatus.value === "connected" ||
      connectionStatus.value === "connecting"
    ) {
      return;
    }

    shouldReconnect = true;
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (!settingsLoaded) {
      void refreshSettings();
    }

    if (typeof window === "undefined" || typeof WebSocket === "undefined") {
      connectionStatus.value = "disconnected";
      return;
    }

    connectionStatus.value = "connecting";

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.hostname}:8000/ws/telemetry`;
    const currentSocket = new WebSocket(wsUrl);
    socket = currentSocket;

    currentSocket.onopen = () => {
      // eslint-disable-next-line no-console
      console.log("Connected to LinuxCNC Telemetry");
      connectionStatus.value = "connected";
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

          eventBus.publish(STATE_TEMPERATURES_TOPIC, {
            temperatures: status.temperatures || {},
          });
        } else if (payload.type === "delta") {
          applyDelta(status, payload.data);

          eventBus.publish(STATE_TEMPERATURES_TOPIC, {
            temperatures: status.temperatures || {},
          });
        } else if (payload.type === "error") {
          errors.value.push(payload.data);
          // eslint-disable-next-line no-console
          console.error("Machine Error:", payload.data.text);
        }
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("Failed to parse websocket message", err);
      }
    };

    currentSocket.onclose = () => {
      // Ignore a close event from a socket that was explicitly replaced
      // or disconnected. This prevents stale sockets from changing the
      // status of a newer connection.
      if (socket !== currentSocket) return;

      // eslint-disable-next-line no-console
      console.warn(
        "WebSocket disconnected. Retrying in 2 seconds...",
      );
      connectionStatus.value = "disconnected";
      socket = null;

      if (shouldReconnect && reconnectTimer === null) {
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null;
          connect();
        }, 2000);
      }
    };

    currentSocket.onerror = (err) => {
      // eslint-disable-next-line no-console
      console.error("WebSocket error:", err);
      if (socket === currentSocket) currentSocket.close();
    };
  }

  function disconnect() {
    shouldReconnect = false;
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }

    const currentSocket = socket;
    // Clear the reference before closing so its asynchronous onclose
    // handler cannot schedule a reconnect during module teardown.
    socket = null;
    if (currentSocket) currentSocket.close();
    connectionStatus.value = "disconnected";

    // Clear any running keep-alive intervals to release timers in
    // case the module is being torn down under a hot-reload.
    for (const axis of Object.keys(jogIntervals)) {
      clearInterval(jogIntervals[axis]);
      delete jogIntervals[axis];
    }
  }

  // ----------------------------------------------------------------- //
  // Hardware actions                                                   //
  // ----------------------------------------------------------------- //

  async function toggleEstop() {
    const consoleStore = useConsoleStore();
    // E-STOP is currently triggered (== 1) means we need to reset
    // it; otherwise we engage it.
    const targetState = status.estop === 1 ? "estop_reset" : "estop";
    try {
      await ModulesMachineService.setMachineState({ state: targetState });
      if (targetState === "estop") {
        consoleStore.addMessage("E-STOP Engaged", "error");
      } else {
        consoleStore.addMessage("E-STOP Cleared", "success");
      }
    } catch (err) {
      consoleStore.addMessage(
        `Failed to toggle ESTOP: ${err.message}`,
        "error",
      );
      // eslint-disable-next-line no-console
      console.error("Failed to toggle ESTOP", err);
    }
  }

  async function togglePower() {
    const consoleStore = useConsoleStore();
    // ``status.task_state`` of 4 == STATE_ON, 3 == STATE_OFF.
    const isOn = status.task_state === 4;
    const isEstop = status.estop === 1;
    if (isEstop && !isOn) {
      consoleStore.addMessage(
        "Cannot turn on machine while ESTOP is active",
        "warning",
      );
      return;
    }
    const targetState = isOn ? "off" : "on";
    try {
      await ModulesMachineService.setMachineState({ state: targetState });
      if (targetState === "on") {
        consoleStore.addMessage("Machine Power ON", "success");
      } else {
        consoleStore.addMessage("Machine Power OFF", "info");
      }
    } catch (err) {
      consoleStore.addMessage(
        `Failed to toggle Power: ${err.message}`,
        "error",
      );
      // eslint-disable-next-line no-console
      console.error("Failed to toggle Power", err);
    }
  }

  async function jog(axis, distance) {
    const consoleStore = useConsoleStore();
    const axisName = AXIS_NAMES[axis];
    try {
      if (!settingsLoaded) await refreshSettings();
      const velocity = Number.isFinite(defaultJogVelocity.value)
        ? defaultJogVelocity.value
        : DEFAULT_JOG_VELOCITY;
      consoleStore.addMessage(
        `Jogging ${axisName} axis ${distance}mm`,
        "info",
      );
      await ModulesMachineService.jogAxis({
        velocities: { [axis]: velocity },
        distance,
      });
    } catch (err) {
      consoleStore.addMessage(
        `Failed to jog ${axisName}: ${err.message}`,
        "error",
      );
      // eslint-disable-next-line no-console
      console.error("Failed to jog axis", axis, err);
    }
  }

  async function jogContinuous(axis, velocity) {
    const consoleStore = useConsoleStore();
    const axisName = AXIS_NAMES[axis];
    try {
      // Load persisted defaults before the first jog if the module was
      // mounted before its settings request completed.
      if (!settingsLoaded) await refreshSettings();

      const requestedVelocity = Number(velocity);
      const jogVelocity = Number.isFinite(requestedVelocity)
        ? requestedVelocity
        : defaultJogVelocity.value;
      const intervalMs = Number.isFinite(keepaliveIntervalMs.value)
        ? keepaliveIntervalMs.value
        : DEFAULT_KEEPALIVE_INTERVAL_MS;

      // 1. Clear any existing interval to prevent ghost loops.
      if (jogIntervals[axis]) {
        clearInterval(jogIntervals[axis]);
        delete jogIntervals[axis];
      }

      // 2. Send the initial start command.
      consoleStore.addMessage(
        `Jogging ${axisName} axis continuously...`,
        "info",
      );
      await ModulesMachineService.jogAxis({
        velocities: { [axis]: jogVelocity },
        distance: 0,
      });

      // 3. Start the keep-alive loop. The cadence is a persisted
      // module setting, with the historical 250 ms value as fallback.
      jogIntervals[axis] = setInterval(async () => {
        try {
          await ModulesMachineService.jogKeepalive({ axes: [axis] });
        } catch (err) {
          // eslint-disable-next-line no-console
          console.error(
            `Keepalive ping failed for axis ${axis}:`,
            err,
          );
        }
      }, intervalMs);
    } catch (err) {
      consoleStore.addMessage(
        `Failed to start continuous jog: ${err.message}`,
        "error",
      );
      // eslint-disable-next-line no-console
      console.error("Failed to start continuous jog", err);
    }
  }

  async function jogStop(axis) {
    const consoleStore = useConsoleStore();
    const axisName = AXIS_NAMES[axis];
    try {
      // 1. Clear the keep-alive loop.
      if (jogIntervals[axis]) {
        clearInterval(jogIntervals[axis]);
        delete jogIntervals[axis];
      }

      // 2. Send the explicit stop command.
      await ModulesMachineService.jogStop({ axes: [axis] });
      consoleStore.addMessage(`${axisName} Jog stopped`, "info");
    } catch (err) {
      consoleStore.addMessage(
        `Failed to stop jog: ${err.message}`,
        "error",
      );
      // eslint-disable-next-line no-console
      console.error("Failed to stop jog", err);
    }
  }

  async function homeAxis(axisIndex) {
    const consoleStore = useConsoleStore();
    try {
      consoleStore.addMessage(`Homing axis index ${axisIndex}...`, "info");
      await ModulesMachineService.homeAxis({ axis: axisIndex });
      consoleStore.addMessage(
        `Homed axis ${axisIndex} successfully`,
        "success",
      );
    } catch (err) {
      consoleStore.addMessage(
        `Failed to home axis ${axisIndex}: ${err.message}`,
        "error",
      );
      // eslint-disable-next-line no-console
      console.error("Failed to home axis", axisIndex, err);
    }
  }

  async function homeAll() {
    const consoleStore = useConsoleStore();
    try {
      consoleStore.addMessage("Homing all axes...", "info");
      await ModulesMachineService.homeAxis({ axis: HOME_ALL });
      consoleStore.addMessage("All axes homed successfully", "success");
    } catch (err) {
      consoleStore.addMessage(
        `Failed to home all axes: ${err.message}`,
        "error",
      );
      // eslint-disable-next-line no-console
      console.error("Failed to home all axes", err);
    }
  }

  async function setPosition(axisIndex, value) {
    const consoleStore = useConsoleStore();
    const axisName = AXIS_NAMES[axisIndex];
    if (!axisName) return;
    try {
      consoleStore.addMessage(
        `Setting work offset for ${axisName} to ${value}...`,
        "command",
      );
      const cmd = generateSetOffset(axisName, value);
      await ModulesMachineService.runMdiCommand({ command: cmd });
    } catch (err) {
      consoleStore.addMessage(
        `Failed to set position for ${axisName}: ${err.message}`,
        "error",
      );
      // eslint-disable-next-line no-console
      console.error("Failed to set position for axis", axisIndex, err);
    }
  }

  async function setCoordinateSystem(gcodeString) {
    const consoleStore = useConsoleStore();
    try {
      consoleStore.addMessage(
        `Switching to Coordinate System: ${gcodeString}`,
        "command",
      );
      await ModulesMachineService.runMdiCommand({ command: gcodeString });
    } catch (err) {
      consoleStore.addMessage(
        `Failed to switch Coordinate System: ${err.message}`,
        "error",
      );
      // eslint-disable-next-line no-console
      console.error("Failed to switch coordinate system", err);
    }
  }

  // ----------------------------------------------------------------- //
  // Public surface                                                     //
  // ----------------------------------------------------------------- //

  return {
    // Reactive state.
    connectionStatus,
    status,
    errors,
    jogIntervals,
    defaultJogVelocity,
    keepaliveIntervalMs,
    isUpdating,
    // Derived values (formally getters).
    droX,
    droY,
    droZ,
    isEstop,
    isMachineOn,
    machineStateText,
    // WebSocket transport.
    connect,
    disconnect,
    refreshSettings,
    // Hardware actions.
    toggleEstop,
    togglePower,
    jog,
    jogContinuous,
    jogStop,
    homeAxis,
    homeAll,
    setPosition,
    setCoordinateSystem,
  };
});

/**
 * Helper that wraps :func:`storeToRefs` so callers can destructure
 * the reactive state without losing reactivity. Re-exported here so
 * module consumers have a single import surface.
 *
 * @returns {{store: import('pinia').Store, ...import('vue').ToRefs<...>}}
 */
export function useMachineRefs() {
  const store = useMachineStore();
  return { store, ...storeToRefs(store) };
}

export default useMachineStore;
