import { defineStore } from 'pinia'
import { api } from '../services/api'
import { useConsoleStore } from './console'

// Axis index to G-code letter mapping (X=0, Y=1, Z=2)
const AXIS_NAMES = ['X', 'Y', 'Z'];

// Sentinel value accepted by the backend /machine/home endpoint to home all axes
const HOME_ALL_AXES = -1;

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
      actual_temp: 0.0
    },
    // Multi-sensor temperatures dictionary (populated from telemetry)
    temperatures: {},
    errors: [],
    socket: null,
    isUpdating: false,
    jogIntervals: {}, // Map to hold active interval IDs for each axis
    temperatureHistory: [] // Array of { time: timestamp, actual: temp, target: temp }
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
      
      // Use the Vite proxy if in dev, or standard host in prod
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/ws/telemetry`;
      
      this.socket = new WebSocket(wsUrl);
      
      this.socket.onopen = () => {
        console.log("Connected to LinuxCNC Telemetry");
        this.connectionStatus = 'connected';
      };
      
      this.socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          
          if (payload.type === 'status') {
            // Merge status and temperatures separately to keep shape predictable
            const sensors = payload.data.temperatures || {};
            this.$patch({
              status: payload.data,
              temperatures: sensors
            });

            // Append to temperature history array as a snapshot of sensor values
            const now = new Date();
            const timeLabel = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;

            this.temperatureHistory.push({
              time: timeLabel,
              sensors: sensors
            });

            // Keep a rolling window of 100 data points to prevent memory leaks
            if (this.temperatureHistory.length > 100) {
              this.temperatureHistory.shift();
            }
            
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

    // --- Hardware Control Actions ---
    
    async toggleEstop() {
      const consoleStore = useConsoleStore();
      // If currently Estopped, send Reset. Otherwise send Estop.
      const targetState = this.isEstop ? 'estop_reset' : 'estop';
      try {
        await api.setMachineState(targetState);
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
        await api.setMachineState(targetState);
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
        await api.jogAxis(axis, velocity, distance);
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
        await api.jogAxis(axis, velocity, 0);

        // 3. Start the Keep-Alive loop
        this.jogIntervals[axis] = setInterval(async () => {
          try {
            await api.jogKeepalive(axis);
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
        await api.jogStop(axis);
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
        await api.homeAxis(axisIndex);
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
        await api.homeAxis(HOME_ALL_AXES);
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
        await api.setWorkOffset(axisName, value);
      } catch (e) {
        consoleStore.addMessage(`Failed to set position for ${axisName}: ${e.message}`, 'error')
        console.error("Failed to set position for axis", axisIndex, e);
      }
    },

    async setCoordinateSystem(gcodeString) {
      const consoleStore = useConsoleStore()
      try {
        consoleStore.addMessage(`Switching to Coordinate System: ${gcodeString}`, 'command')
        await api.setCoordinateSystem(gcodeString);
      } catch (e) {
        consoleStore.addMessage(`Failed to switch Coordinate System: ${e.message}`, 'error')
        console.error("Failed to switch coordinate system", e);
      }
    },
    
    async setTargetTemperature(sensorName, targetValue) {
      const consoleStore = useConsoleStore()
      try {
        consoleStore.addMessage(`Setting ${sensorName} target temperature to ${targetValue}°C`, 'command')
        await api.setTargetTemperature(sensorName, targetValue);
      } catch (e) {
        consoleStore.addMessage(`Failed to set ${sensorName} target temperature: ${e.message}`, 'error')
        console.error("Failed to set temperature", e);
      }
    }
  }
})