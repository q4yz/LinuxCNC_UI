import { generateSetOffset } from '../config/gcodes';

const API_BASE_URL = `http://${window.location.hostname}:8000/api/v1`;

async function postJson(endpoint, payload = {}) {
  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });
    
    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`API Error (${response.status}): ${errText}`);
    }
    
    return await response.json();
  } catch (err) {
    console.error(`POST ${endpoint} failed:`, err);
    throw err;
  }
}

export const api = {
  // Machine State Control
  setMachineState: (state) => postJson('/machine/state', { state }), // 'on', 'off', 'estop', 'estop_reset'
  setMachineMode: (mode) => postJson('/machine/mode', { mode }),     // 'manual', 'auto', 'mdi'
  
  // Movement
  homeAxis: (axis) => postJson('/machine/home', { axis }),
  jogAxis: (axisOrVelocities, velocity, distance = 0) => {
    if (axisOrVelocities && typeof axisOrVelocities === 'object' && !Array.isArray(axisOrVelocities)) {
      return postJson('/machine/jog', axisOrVelocities);
    }

    return postJson('/machine/jog', {
      velocities: { [axisOrVelocities]: velocity },
      distance,
    });
  },
  jogKeepalive: async (axes) => {
    const axisList = Array.isArray(axes) ? axes : [axes];
    return postJson('/machine/jog/keepalive', { axes: axisList });
  },
  jogStop: (axes) => {
    const axisList = Array.isArray(axes) ? axes : [axes];
    return postJson('/machine/jog/stop', { axes: axisList });
  },
  sendMdiCommand: (command) => postJson('/machine/mdi', { command }),
  
  // Work Offsets
  setWorkOffset: (axisName, value) => {
    const cmd = generateSetOffset(axisName, value);
    return postJson('/machine/mdi', { command: cmd });
  },
  setCoordinateSystem: (gcodeStr) => postJson('/machine/mdi', { command: gcodeStr }),

  // Temperatures
  setTargetTemperature: (sensorName, targetValue) => postJson('/machine/temperature', { sensor_name: sensorName, target: parseFloat(targetValue) }),
  
  // Program Execution
  runProgram: (lineNumber = 0) => postJson(`/program/run?line_number=${lineNumber}`),
  stopProgram: () => postJson('/program/stop'),
  pauseProgram: () => postJson('/program/pause'),
  resumeProgram: () => postJson('/program/resume'),

  // Files
  fetchFiles: async () => {
    const res = await fetch(`${API_BASE_URL}/ncfiles`);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  uploadFile: async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_BASE_URL}/ncfiles/upload`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  deleteFile: async (filename) => {
    const res = await fetch(`${API_BASE_URL}/ncfiles/${encodeURIComponent(filename)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  loadProgram: (filename) => postJson('/file/load', { filename }),
  loadProgram: (filename) => postJson('/files/load_program', { filename }),

  // Configs
  fetchConfigs: async () => {
      const res = await fetch(`${API_BASE_URL}/config`);
      if (!res.ok) throw new Error(await res.text());
      return res.json();
  },
  // Compiler Pipeline
  fetchCompilerProfiles: async () => {
      const res = await fetch(`${API_BASE_URL}/compiler/profiles`);
      if (!res.ok) throw new Error(await res.text());
      return res.json();
  },
  generateCompilerProfile: (profileName) => postJson(`/compiler/generate/${encodeURIComponent(profileName)}`),
  deployCompilerStage: () => postJson('/compiler/deploy'),

  generateProfile: async (filename) => {
      try {
          const res = await fetch(`${API_BASE_URL}/config/compile/generate/${encodeURIComponent(filename)}`, {
              method: 'POST',
              headers: {
                  'Content-Type': 'application/json'
              },
          })

          if (!res.ok) {
              let detail = ''
              try {
                  const errorBody = await res.json()
                  detail = errorBody?.detail || ''
              } catch {
                  detail = await res.text()
              }
              throw new Error(detail || `API Error (${res.status})`)
          }

          return res.json()
      } catch (err) {
          throw new Error(err.response?.data?.detail || err.message)
      }
  },

  readConfig: async (filename) => {
    const res = await fetch(`${API_BASE_URL}/config/${encodeURIComponent(filename)}`);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  saveConfig: (filename, content) => postJson(`/config/${encodeURIComponent(filename)}`, { content }),
  
  // Parser
  triggerParser: () => postJson('/config/parse')
  ,
  // System utilities
  triggerUpdate: () => postJson('/system/update', {}),
  getVersionInfo: async () => {
    const res = await fetch(`${API_BASE_URL}/system/version`)
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  }
};