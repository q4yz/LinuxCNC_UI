import { defineStore } from 'pinia'
import { generateSetOffset } from '../config/gcodes'
import { JoggingService } from '../../generated/api/services/JoggingService'
import { MachineStateService } from '../../generated/api/services/MachineStateService'
import { useConsoleStore } from './console'
import { eventBus } from '../core/modules/event-bus'

// Axis index to G-code letter mapping (X=0, Y=1, Z=2)
const AXIS_NAMES = ['X', 'Y', 'Z'];

// Sentinel value accepted by the backend /machine/home endpoint to home all axes
const HOME_ALL_AXES = -1;

// Bus topic published by the temperature module (and subscribed by
// us as a thin pass-through). Anything pushed to this topic keeps the
// legacy ``temperatures`` reference in sync so unmigrated consumers
// (``DebugPanel.vue`` and any third-party widget) keep working.
const STATE_TEMPERATURES_TOPIC = 'state.temperatures'

const isPlainObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

const applyDelta = (target, delta) => {
  if (!isPlainObject(target) || !isPlainObject(delta)) {
    return target;
  }

  Object.keys(delta).forEach((key) => {
    const deltaValue = delta[key];

    if (isPlainObject(deltaValue)) {
      if (!isPlainObject(target[key])) {
        target[key] = {};
      }
      applyDelta(target[key], deltaValue);
    } else {
      target[key] = deltaValue;
    }
  });

  return target;
};

export const useMachineStore = defineStore('machine', {
  state: () => ({
    connectionStatus: 'disconnected', // 'disconnected', 'connecting', 'connected'
    status: {
      task_state: 1, // 1=ESTOP, 2=ESTOP_RESET, 3=OFF, 4=ON
      estop: 1,      // 1=Triggered, 0=Clear
      task_mode: 1,  // 1=MANUAL, 2=AUTO, 3=MDI
      position: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
      actual_position: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
      relative_position: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
      state: 1,
      file: "",
      homed: [0, 0, 0],
      interp_state: 1,
      current_line: 0,
      g5x_index: 1,
      target_temp: 0.0,
      actual_temp: 0.0,
      temperatures: {}
    },
    // Multi-sensor temperatures dictionary (populated from telemetry)
    temperatures: {},
    errors: [],
    socket: null,
    isUpdating: false,
    jogIntervals: {}, // Map to hold active interval IDs for each axis
    // Legacy ``temperatureHistory`` and ``temperaturePollingInterval``
    // removed in issue #32. The rolling chart history now lives in
    // the temperature module's Pinia store
    // (``frontend/src/modules/temperature/store.js``).
  }),

  getters: {
    // Format coordinates to 3 decimal places for the DRO
    droX: (state) => state.status.relative_position[0].toFixed(3),
    droY: (state) => state.status.relative_position[1].toFixed(3),
    droZ: (state) => state.status.relative_position[2].toFixed(3),
    
    // Derived booleans for UI state
    isEstop: (state) => state.status.estop === 1,
    isMachineOn: (state) => state.status.task_state === 4,
    
    // Status text mapping
    machineStateText: (state) => {
      if (state.status.estop === 1) return 'ESTOP';
      if (state.status.task_state === 3) return 'OFF';
      if (state.status.task_state === 4) return 'ON';
      return 'READY';
    }
  },

  actions: {
    connect() {
      if (this.connectionStatus === 'connected' || this.connectionStatus === 'connecting') return;
      
      this.connectionStatus = 'connecting';
      
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.hostname}:8000/ws/telemetry`;
      
      this.socket = new WebSocket(wsUrl);
      
      this.socket.onopen = () => {
        console.log("Connected to LinuxCNC Telemetry");
        this.connectionStatus = 'connected';
      };
      
      this.socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          
          if (payload.type === 'full_state') {
            // Full state: replace entire status and republish to bus
            // so module stores (e.g. temperature) can pick it up.
            this.status = payload.data;
            this.temperatures = this.status.temperatures || {};
            eventBus.publish(STATE_TEMPERATURES_TOPIC, {
              temperatures: this.status.temperatures || {},
            });

          } else if (payload.type === 'delta') {
            // Delta: merge into existing status, then sync temperatures reference
            applyDelta(this.status, payload.data);
            
            // Always sync this.temperatures to the fully-merged this.status.temperatures
            // This ensures the UI stays in sync with merged state, not just the last delta
            this.temperatures = this.status.temperatures || {};
            // Republish the merged view so the temperature module's
            // store can ingest the latest values via the event bus.
            eventBus.publish(STATE_TEMPERATURES_TOPIC, {
              temperatures: this.status.temperatures || {},
            });
            
          } else if (payload.type === 'error') {
            this.errors.push(payload.data);
            console.error("Machine Error:", payload.data.text);
          }
        } catch (e) {
          console.error("Failed to parse websocket message", e);
        }
      };
      
      this.socket.onclose = () => {
        console.warn("WebSocket disconnected. Retrying in 2 seconds...");
        this.connectionStatus = 'disconnected';
        this.socket = null;
        
        // Auto-reconnect
        setTimeout(() => {
          this.connect();
        }, 2000);
      };
      
      this.socket.onerror = (err) => {
        console.error("WebSocket error:", err);
        // onclose will handle the reconnection
        if (this.socket) {
          this.socket.close();
        }
      };
    },

    disconnect() {
      // Explicitly disconnect and clean up resources
      if (this.socket) {
        this.socket.close();
        this.socket = null;
      }
      
      this.connectionStatus = 'disconnected';
    },

    // --- Hardware Control Actions ---
    
    async toggleEstop() {
      const consoleStore = useConsoleStore();
      // If currently Estopped, send Reset. Otherwise send Estop.
      const targetState = this.isEstop ? 'estop_reset' : 'estop';
      try {
        await MachineStateService.setMachineState({ state: targetState });
        if (targetState === 'estop') {
          consoleStore.addMessage("E-STOP Engaged", 'error');
        } else {
          consoleStore.addMessage("E-STOP Cleared", 'success');
        }
      } catch (e) {
        consoleStore.addMessage(`Failed to toggle ESTOP: ${e.message}`, 'error');
        console.error("Failed to toggle ESTOP", e);
      }
    },

    async togglePower() {
      const consoleStore = useConsoleStore();
      // Cannot power on if ESTOP is active
      if (this.isEstop && !this.isMachineOn) {
        consoleStore.addMessage("Cannot turn on machine while ESTOP is active", 'warning');
        return;
      }
      const targetState = this.isMachineOn ? 'off' : 'on';
      try {
        await MachineStateService.setMachineState({ state: targetState });
        if (targetState === 'on') {
          consoleStore.addMessage("Machine Power ON", 'success');
        } else {
          consoleStore.addMessage("Machine Power OFF", 'info');
        }
      } catch (e) {
        consoleStore.addMessage(`Failed to toggle Power: ${e.message}`, 'error');
        console.error("Failed to toggle Power", e);
      }
    },

    async jog(axis, distance) {
      const consoleStore = useConsoleStore();
      // axis: 0=X, 1=Y, 2=Z
      // Standard velocity for UI testing
      const velocity = 500;
      const axisName = AXIS_NAMES[axis];

      // Ensure the machine is in manual mode first, though the backend handles this
      try {
        consoleStore.addMessage(`Jogging ${axisName} axis ${distance}mm`, 'info');
        await JoggingService.jogAxis({
          velocities: { [axis]: velocity },
          distance,
        });
      } catch (e) {
        consoleStore.addMessage(`Failed to jog ${axisName}: ${e.message}`, 'error');
        console.error("Failed to jog axis", axis, e);
      }
    },

    async jogContinuous(axis, velocity) {
      const consoleStore = useConsoleStore();
      const axisName = AXIS_NAMES[axis];
      try {
        // 1. Clear any existing interval to prevent ghost loops
        if (this.jogIntervals[axis]) {
          clearInterval(this.jogIntervals[axis]);
        }

        // 2. Send the initial Start command
        consoleStore.addMessage(`Jogging ${axisName} axis continuously...`, 'info');
        await JoggingService.jogAxis({
          velocities: { [axis]: velocity },
          distance: 0,
        });

        // 3. Start the Keep-Alive loop
        this.jogIntervals[axis] = setInterval(async () => {
          try {
            await JoggingService.jogKeepalive({ axes: [axis] });
          } catch (e) {
            console.error(`Keepalive ping failed for axis ${axis}:`, e);
          }
        }, 250);

      } catch (e) {
        consoleStore.addMessage(`Failed to start continuous jog: ${e.message}`, 'error');
        console.error("Failed to start continuous jog", e);
      }
    },

    async jogStop(axis) {
      const consoleStore = useConsoleStore();
      const axisName = AXIS_NAMES[axis];
      try {
        // 1. Clear the Keep-Alive loop
        if (this.jogIntervals[axis]) {
          clearInterval(this.jogIntervals[axis]);
          delete this.jogIntervals[axis];
        }

        // 2. Send the explicit Stop command
        await JoggingService.jogStop({ axes: [axis] });
        consoleStore.addMessage(`${axisName} Jog stopped`, 'info');
      } catch (e) {
        consoleStore.addMessage(`Failed to stop jog: ${e.message}`, 'error');
        console.error("Failed to stop jog", e);
      }
    },

    async homeAxis(axisIndex) {
      const consoleStore = useConsoleStore()
      try {
        consoleStore.addMessage(`Homing axis index ${axisIndex}...`, 'info')
        await MachineStateService.homeAxis({ axis: axisIndex });
        consoleStore.addMessage(`Homed axis ${axisIndex} successfully`, 'success')
      } catch (e) {
        consoleStore.addMessage(`Failed to home axis ${axisIndex}: ${e.message}`, 'error')
        console.error(`Failed to home axis ${axisIndex}`, e);
      }
    },

    async homeAll() {
      const consoleStore = useConsoleStore()
      try {
        consoleStore.addMessage("Homing all axes...", 'info')
        await MachineStateService.homeAxis({ axis: HOME_ALL_AXES });
        consoleStore.addMessage("All axes homed successfully", 'success')
      } catch (e) {
        consoleStore.addMessage(`Failed to home all axes: ${e.message}`, 'error')
        console.error("Failed to home all axes", e);
      }
    },

    async setPosition(axisIndex, value) {
      const consoleStore = useConsoleStore()
      const axisName = AXIS_NAMES[axisIndex];
      if (!axisName) return;
      try {
        consoleStore.addMessage(`Setting work offset for ${axisName} to ${value}...`, 'command')
        const cmd = generateSetOffset(axisName, value);
        await MachineStateService.runMdiCommand({ command: cmd });
      } catch (e) {
        consoleStore.addMessage(`Failed to set position for ${axisName}: ${e.message}`, 'error')
        console.error("Failed to set position for axis", axisIndex, e);
      }
    },

    async setCoordinateSystem(gcodeString) {
      const consoleStore = useConsoleStore()
      try {
        consoleStore.addMessage(`Switching to Coordinate System: ${gcodeString}`, 'command')
        await MachineStateService.runMdiCommand({ command: gcodeString });
      } catch (e) {
        consoleStore.addMessage(`Failed to switch Coordinate System: ${e.message}`, 'error')
        console.error("Failed to switch coordinate system", e);
      }
    },

    async setTargetTemperature(sensorName, targetValue) {
      // Legacy wrapper kept so any third-party widget still importing
      // ``useMachineStore().setTargetTemperature`` keeps working.
      // The temperature module's panel now calls the temperature
      // module's HTTP endpoint directly; this action routes through
      // the module's ``/api/v1/modules/temperature/sensors/{name}/target``
      // endpoint. ``MachineStateService.setTargetTemperature`` is no
      // longer generated by the backend, so we use a hand-written
      // fetch.
      const consoleStore = useConsoleStore()
      try {
        consoleStore.addMessage(`Setting ${sensorName} target temperature to ${targetValue}°C`, 'command')
        const res = await fetch(
          `/api/v1/modules/temperature/sensors/${encodeURIComponent(sensorName)}/target`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              sensor_name: sensorName,
              target: parseFloat(targetValue),
            }),
          },
        )
        if (!res.ok) {
          const detail = await res.text().catch(() => res.statusText)
          throw new Error(`set target failed: ${res.status} ${detail}`)
        }
      } catch (e) {
        consoleStore.addMessage(`Failed to set ${sensorName} target temperature: ${e.message}`, 'error')
        console.error("Failed to set temperature", e);
      }
    }
  }
})

// ---------------------------------------------------------------------------
// Pass-through bus subscription.
//
// ``useTemperatureStore`` (the new module-scoped store under the
// ``module_temperature`` id) is the source of truth for temperature
// data once issue #32 lands. This subscription keeps the legacy
// ``temperatures`` field on this store in sync via the event bus so
// components that have not migrated yet (e.g. ``DebugPanel.vue``,
// which renders ``JSON.stringify(useMachineStore())``) keep showing
// the live values. The bus delivers a deep-frozen, deep-cloned copy
// of every published payload (Gotcha #3), so subscribing to our own
// publication does not cause a feedback loop — we receive a fresh
// copy that is safe to assign.
//
// We subscribe at module load time because the legacy store has no
// teardown lifecycle; the subscription lives for the lifetime of the
// page, matching the WebSocket subscription above.
// ---------------------------------------------------------------------------
if (typeof window !== 'undefined' && eventBus && typeof eventBus.subscribe === 'function') {
  eventBus.subscribe(STATE_TEMPERATURES_TOPIC, (_topic, payload) => {
    if (!payload || typeof payload !== 'object') return;
    const next = payload.temperatures;
    if (next && typeof next === 'object') {
      // The bus hands us a frozen copy. Pinia state wants a plain
      // object, so we keep the reference as-is — Pinia does not
      // mutate, it only reads.
      useMachineStore().temperatures = next;
    }
  });
}