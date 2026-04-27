import { defineStore } from 'pinia'
import { api } from '../services/api'

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
      state: 1,
      file: "",
      homed: [0, 0, 0],
      interp_state: 1,
      current_line: 0
    },
    errors: [],
    socket: null,
    jogIntervals: {} // Map to hold active interval IDs for each axis
  }),

  getters: {
    // Format coordinates to 3 decimal places for the DRO
    droX: (state) => state.status.position[0].toFixed(3),
    droY: (state) => state.status.position[1].toFixed(3),
    droZ: (state) => state.status.position[2].toFixed(3),
    
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
          console.log('WS Payload:', payload); // Added for debugging visibility
          
          if (payload.type === 'status') {
            // Use Pinia's $patch for safe, deep reactivity merging
            this.$patch({
              status: payload.data
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

    // --- Hardware Control Actions ---
    
    async toggleEstop() {
      // If currently Estopped, send Reset. Otherwise send Estop.
      const targetState = this.isEstop ? 'estop_reset' : 'estop';
      try {
        await api.setMachineState(targetState);
      } catch (e) {
        console.error("Failed to toggle ESTOP", e);
      }
    },

    async togglePower() {
      // Cannot power on if ESTOP is active
      if (this.isEstop && !this.isMachineOn) {
        console.warn("Cannot turn on machine while ESTOP is active");
        return;
      }
      const targetState = this.isMachineOn ? 'off' : 'on';
      try {
        await api.setMachineState(targetState);
      } catch (e) {
        console.error("Failed to toggle Power", e);
      }
    },

    async jog(axis, distance) {
      // axis: 0=X, 1=Y, 2=Z
      // Standard velocity for UI testing
      const velocity = 500;
      
      // Ensure the machine is in manual mode first, though the backend handles this
      try {
        await api.jogAxis(axis, velocity, distance);
      } catch (e) {
        console.error("Failed to jog axis", axis, e);
      }
    },

    async jogContinuous(axis, velocity) {
      try {
        // 1. Clear any existing interval to prevent ghost loops
        if (this.jogIntervals[axis]) {
          clearInterval(this.jogIntervals[axis]);
        }

        // 2. Send the initial Start command
        console.log(`Starting continuous jog on axis ${axis} at velocity ${velocity}`);
        await api.jogAxis(axis, velocity, 0);

        // 3. Start the Keep-Alive loop
        this.jogIntervals[axis] = setInterval(async () => {
          console.log(`Ping Keepalive for axis ${axis}`);
          try {
            await api.jogKeepalive(axis);
          } catch (e) {
            console.error(`Keepalive ping failed for axis ${axis}:`, e);
          }
        }, 250);

      } catch (e) {
        console.error("Failed to start continuous jog", e);
      }
    },

    async jogStop(axis) {
      try {
        console.log(`Stopping jog on axis ${axis}`);
        // 1. Clear the Keep-Alive loop
        if (this.jogIntervals[axis]) {
          clearInterval(this.jogIntervals[axis]);
          delete this.jogIntervals[axis];
        }

        // 2. Send the explicit Stop command
        await api.jogStop(axis);
      } catch (e) {
        console.error("Failed to stop jog", e);
      }
    },

    async homeAxis(axis) {
      try {
        await api.homeAxis(axis);
      } catch (e) {
        console.error("Failed to home axis", axis, e);
      }
    },

    async homeAll() {
      try {
        await api.homeAxis(HOME_ALL_AXES);
      } catch (e) {
        console.error("Failed to home all axes", e);
      }
    },

    async setPosition(axis, value) {
      const axisName = AXIS_NAMES[axis];
      if (!axisName) return;
      try {
        await api.sendMdi(`G92 ${axisName}${value}`);
      } catch (e) {
        console.error("Failed to set position for axis", axis, e);
      }
    }
  }
})