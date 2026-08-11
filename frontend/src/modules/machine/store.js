// Machine module Pinia store. Owns the WebSocket transport, the
// reactive full-state object, the per-axis keep-alive handles, and
// every hardware/program-lifecycle action. The temperature fields
// are republished on the event bus so the temperature module can
// ingest updates without owning the transport. See
// ``.agent/STATE.md`` § 2 (store id rule), § 6 (state facade).

import { defineStore, storeToRefs } from "pinia";
import { computed, reactive, ref } from "vue";

import manifest from "./manifest.js";
import { generateSetOffset } from "../../config/gcodes.js";
import { ModulesMachineService } from "../../../generated/api/services/ModulesMachineService";
import { ModulesProgramService } from "../../../generated/api/services/ModulesProgramService";
import { useConsoleStore } from "../../stores/console.js";
import { createModuleSettings } from "../../core/modules/settings.js";
import { eventBus } from "../../core/modules/event-bus.js";
import { useMachineStore as useMachineFacadeStore } from "../../stores/machineStore.js";

// Axis index → letter mapping (matches ``gcodes.js`` conventions).
const AXIS_NAMES = ["X", "Y", "Z"];

// Sentinel accepted by the backend ``/home`` endpoint to home all axes.
const HOME_ALL = -1;
const DEFAULT_JOG_VELOCITY = 500;
const DEFAULT_KEEPALIVE_INTERVAL_MS = 250;

// Bus topic the machine store publishes so the temperature module
// can ingest sensor updates without owning the WebSocket transport.
const STATE_TEMPERATURES_TOPIC = "state.temperatures";
const machineSettings = createModuleSettings(manifest.id);

// ``module_`` prefix prevents collisions with legacy top-level
// stores. See ``.agent/STATE.md`` § 2.
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
  // --- Reactive state ---------------------------------------------- //

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
    // Stays 0 until the backend publishes it; ``printProgress``
    // collapses to 0 by contract when the total is unknown.
    total_lines: 0,
    g5x_index: 1,
  });
  const errors = ref([]);
  const jogIntervals = reactive({});
  const defaultJogVelocity = ref(DEFAULT_JOG_VELOCITY);
  const keepaliveIntervalMs = ref(DEFAULT_KEEPALIVE_INTERVAL_MS);
  const isUpdating = ref(false);

  // --- Derived values ----------------------------------------------- //

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

  // ``isPrinting`` and ``isPaused`` are mutually exclusive: a paused
  // program is *not* reported as printing so the widget can swap its
  // "Pause" button for "Resume" without flickering.

  const isPrinting = computed(
    () => status.task_state === 2 && status.interp_state !== 3,
  );
  const isPaused = computed(
    () => status.task_state === 2 && status.interp_state === 3,
  );
  const printProgress = computed(() => {
    const total = Number(status.total_lines);
    const current = Number(status.current_line);
    if (!Number.isFinite(total) || total <= 0) return 0;
    if (!Number.isFinite(current) || current < 0) return 0;
    return Math.min(100, (current / total) * 100);
  });

  // --- Non-reactive handles ----------------------------------------- //

  let socket = null;
  let reconnectTimer = null;
  let shouldReconnect = true;
  let settingsLoaded = false;

  // --- Module settings ------------------------------------------------- //

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

  // --- WebSocket transport ------------------------------------------ //

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
      useMachineFacadeStore().updateStatus({
        connectionStatus: connectionStatus.value,
        isUpdating: isUpdating.value,
        status: { ...status },
      });
      return;
    }

    connectionStatus.value = "connecting";
    useMachineFacadeStore().updateStatus({
      connectionStatus: connectionStatus.value,
      isUpdating: isUpdating.value,
      status: { ...status },
    });

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
      useMachineFacadeStore().updateStatus({
        connectionStatus: connectionStatus.value,
        isUpdating: isUpdating.value,
        status: { ...status },
      });
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

          // Mirror raw telemetry to the State Facade. See
          // ``.agent/STATE.md`` § 6.
          useMachineFacadeStore().updateStatus({
            connectionStatus: connectionStatus.value,
            isUpdating: isUpdating.value,
            status: next,
          });

          eventBus.publish(STATE_TEMPERATURES_TOPIC, {
            temperatures: status.temperatures || {},
          });

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

          // Forward the post-delta snapshot to the facade.
          useMachineFacadeStore().updateStatus({
            connectionStatus: connectionStatus.value,
            isUpdating: isUpdating.value,
            status: { ...status },
          });

          eventBus.publish(STATE_TEMPERATURES_TOPIC, {
            temperatures: status.temperatures || {},
          });
        } else if (payload.type === "error") {
          errors.value.push(payload.data);
          // Route the event through the global console store so the
          // operator's ``ConsolePanel`` renders the row and the toast
          // fires. ``popup: true`` is required because
          // ``core/console.js`` short-circuits ``_emitToast`` when the
          // flag is missing — that was the silent-bug the previous
          // round shipped.
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
      // replaced. Prevents stale sockets from changing the status of
      // a newer connection.
      if (socket !== currentSocket) return;

      // eslint-disable-next-line no-console
      console.warn(
        "WebSocket disconnected. Retrying in 2 seconds...",
      );
      connectionStatus.value = "disconnected";
      socket = null;

      // Mirror to the State Facade so its ``systemState`` reports
      // ``Offline`` immediately.
      useMachineFacadeStore().updateStatus({
        connectionStatus: connectionStatus.value,
        isUpdating: isUpdating.value,
        status: { ...status },
      });

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
    // Clear the reference before closing so the async onclose
    // handler cannot schedule a reconnect during teardown.
    socket = null;
    if (currentSocket) currentSocket.close();
    connectionStatus.value = "disconnected";
    // Mirror to the State Facade so its ``systemState`` reports
    // ``Offline`` immediately.
    useMachineFacadeStore().updateStatus({
      connectionStatus: connectionStatus.value,
      isUpdating: isUpdating.value,
      status: { ...status },
    });

    // Clear any running keep-alive intervals to release timers in
    // case the module is being torn down under a hot-reload.
    for (const axis of Object.keys(jogIntervals)) {
      clearInterval(jogIntervals[axis]);
      delete jogIntervals[axis];
    }
  }

  // --- Hardware actions --------------------------------------------- //

  async function toggleEstop() {
    const consoleStore = useConsoleStore();
    // ``estop == 1`` means we need to reset; otherwise we engage.
    const targetState = status.estop === 1 ? "estop_reset" : "estop";
    try {
      await ModulesMachineService.setMachineState({ state: targetState });
      if (targetState === "estop") {
        consoleStore.warning("E-STOP Engaged");
      } else {
        consoleStore.success("E-STOP Cleared");
      }
    } catch (err) {
      consoleStore.error(
        `Failed to toggle ESTOP: ${err.message}`,

      );
      // eslint-disable-next-line no-console
      console.error("Failed to toggle ESTOP", err);
    }
  }

  async function togglePower() {
    const consoleStore = useConsoleStore();
    // ``task_state`` 4 == ON, 3 == OFF.
    const isOn = status.task_state === 4;
    const isEstop = status.estop === 1;
    if (isEstop && !isOn) {
      consoleStore.warning(
        "Cannot turn on machine while ESTOP is active",
      );
      return;
    }
    const targetState = isOn ? "off" : "on";
    try {
      await ModulesMachineService.setMachineState({ state: targetState });
      if (targetState === "on") {
        consoleStore.success("Machine Power ON");
      } else {
        consoleStore.success("Machine Power OFF");
      }
    } catch (err) {
      consoleStore.error(
        `Failed to toggle Power: ${err.message}`,
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
      consoleStore.info(
        `Jogging ${axisName} axis ${distance}mm`
      );
      await ModulesMachineService.jogAxis({
        velocities: { [axis]: velocity },
        distance,
      });
    } catch (err) {
      consoleStore.error(
        `Failed to jog ${axisName}: ${err.message}`
      );
      // eslint-disable-next-line no-console
      console.error("Failed to jog axis", axis, err);
    }
  }

  async function jogContinuous(axis, velocity) {
    const consoleStore = useConsoleStore();
    const axisName = AXIS_NAMES[axis];
    try {
      // Load persisted defaults if the module was mounted before
      // its settings request completed.
      if (!settingsLoaded) await refreshSettings();

      const requestedVelocity = Number(velocity);
      const jogVelocity = Number.isFinite(requestedVelocity)
        ? requestedVelocity
        : defaultJogVelocity.value;
      const intervalMs = Number.isFinite(keepaliveIntervalMs.value)
        ? keepaliveIntervalMs.value
        : DEFAULT_KEEPALIVE_INTERVAL_MS;

      // Clear any existing interval to prevent ghost loops.
      if (jogIntervals[axis]) {
        clearInterval(jogIntervals[axis]);
        delete jogIntervals[axis];
      }

      consoleStore.info(
        `Jogging ${axisName} axis continuously...`
      );
      await ModulesMachineService.jogAxis({
        velocities: { [axis]: jogVelocity },
        distance: 0,
      });

      // Keep-alive cadence comes from the persisted module setting
      // (250 ms fallback). The backend watchdog trips at 500 ms.
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
      consoleStore.error(
        `Failed to start continuous jog: ${err.message}`,

      );
      // eslint-disable-next-line no-console
      console.error("Failed to start continuous jog", err);
    }
  }

  async function jogStop(axis) {
    const consoleStore = useConsoleStore();
    const axisName = AXIS_NAMES[axis];
    try {
      if (jogIntervals[axis]) {
        clearInterval(jogIntervals[axis]);
        delete jogIntervals[axis];
      }

      await ModulesMachineService.jogStop({ axes: [axis] });
      consoleStore.info(`${axisName} Jog stopped`);
    } catch (err) {
      consoleStore.error(
        `Failed to stop jog: ${err.message}`
      );
      // eslint-disable-next-line no-console
      console.error("Failed to stop jog", err);
    }
  }

  async function homeAxis(axisIndex) {
    const consoleStore = useConsoleStore();
    try {
      consoleStore.info(`Homing axis index ${axisIndex}...`);
      await ModulesMachineService.homeAxis({ axis: axisIndex });
      consoleStore.success(
        `Homed axis ${axisIndex} successfully`,

      );
    } catch (err) {
      consoleStore.error(
        `Failed to home axis ${axisIndex}: ${err.message}`,
      );
      // eslint-disable-next-line no-console
      console.error("Failed to home axis", axisIndex, err);
    }
  }

  async function homeAll() {
    const consoleStore = useConsoleStore();
    try {
      consoleStore.info("Homing all axes...");
      await ModulesMachineService.homeAxis({ axis: HOME_ALL });
      consoleStore.success("All axes homed successfully");
    } catch (err) {
      consoleStore.error(
        `Failed to home all axes: ${err.message}`,
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
      consoleStore.command(
        `Setting work offset for ${axisName} to ${value}...`
      );
      const cmd = generateSetOffset(axisName, value);
      await ModulesMachineService.runMdiCommand({ command: cmd });
    } catch (err) {
      consoleStore.error(
        `Failed to set position for ${axisName}: ${err.message}`
      );
      // eslint-disable-next-line no-console
      console.error("Failed to set position for axis", axisIndex, err);
    }
  }

  async function setCoordinateSystem(gcodeString) {
    const consoleStore = useConsoleStore();
    try {
      consoleStore.command(
        `Switching to Coordinate System: ${gcodeString}`
      );
      await ModulesMachineService.runMdiCommand({ command: gcodeString });
    } catch (err) {
      consoleStore.error(
        `Failed to switch Coordinate System: ${err.message}`
      );
      // eslint-disable-next-line no-console
      console.error("Failed to switch coordinate system", err);
    }
  }

  // Each action only dispatches the request — the backend's
  // telemetry stream mirrors the new state on the next tick so
  // widgets do not need to maintain local flags.

  async function startProgram(filename) {
    if (!filename || typeof filename !== "string") return;
    const consoleStore = useConsoleStore();
    try {
      // Step 1 of the two-step lifecycle: load the program into
      // the interpreter. The backend (program/router.py) validates
      // the filename against the upload root, calls
      // ``command.program_open``, and returns 200 on success. The
      // widget's reactive state transitions to SystemState.LOADED
      // on the next telemetry tick and the operator presses Start
      // to invoke ``runProgram``.
      consoleStore.command(`Loading program ${filename}...`);
      await ModulesProgramService.loadProgram({ filename });
      consoleStore.success(`Loaded ${filename} — press Start to begin.`);
    } catch (err) {
      consoleStore.error(
        `Failed to load ${filename}: ${err.body?.detail || err.message}`,
      );
      // eslint-disable-next-line no-console
      console.error("Failed to load program", filename, err);
    }
  }

  async function loadProgram(filename) {
    if (!filename || typeof filename !== "string") return;
    const consoleStore = useConsoleStore();
    try {
      await ModulesProgramService.loadProgram({ filename });
    } catch (err) {
      consoleStore.error(
        `Failed to load ${filename}: ${err.body?.detail || err.message}`,
      );
      // eslint-disable-next-line no-console
      console.error("Failed to load program", filename, err);
    }
  }

  async function pauseProgram() {
    const consoleStore = useConsoleStore();
    try {
      consoleStore.info("Pausing program");
      await ModulesProgramService.pauseProgram();
    } catch (err) {
      consoleStore.error(`Failed to pause program: ${err.message}`);
      // eslint-disable-next-line no-console
      console.error("Failed to pause program", err);
    }
  }

  async function resumeProgram() {
    const consoleStore = useConsoleStore();
    try {
      consoleStore.info("Resuming program");
      await ModulesProgramService.resumeProgram();
    } catch (err) {
      consoleStore.error(`Failed to resume program: ${err.message}`);
      // eslint-disable-next-line no-console
      console.error("Failed to resume program", err);
    }
  }

  async function abortProgram() {
    const consoleStore = useConsoleStore();
    try {
      consoleStore.warning("Aborting program");
      await ModulesProgramService.stopProgram();
    } catch (err) {
      consoleStore.error(`Failed to abort program: ${err.message}`);
      // eslint-disable-next-line no-console
      console.error("Failed to abort program", err);
    }
  }

  // --- Public surface ------------------------------------------------ //

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
    isPrinting,
    isPaused,
    printProgress,
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
    // Program lifecycle actions.
    startProgram,
    loadProgram,
    pauseProgram,
    resumeProgram,
    abortProgram,
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
