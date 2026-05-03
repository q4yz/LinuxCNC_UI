import { generateSetOffset } from '../config/gcodes';

const API_BASE = '/api/v1';

async function postJson(endpoint, payload = {}) {
  try {
    const response = await fetch(`${API_BASE}${endpoint}`, {
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
  jogAxis: (axis, velocity, distance) => postJson('/machine/jog', { axis, velocity, distance }),
  jogKeepalive: async (axis) => {
    // Explicit keep-alive function with debugging
    // console.log(`API: Sending keep-alive for axis ${axis}`);
    return postJson('/machine/jog/keepalive', { axis });
  },
  jogStop: (axis) => postJson('/machine/jog/stop', { axis }),
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
    const res = await fetch(`${API_BASE}/files`);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  uploadFile: async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_BASE}/files/upload`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  deleteFile: async (filename) => {
    const res = await fetch(`${API_BASE}/files/${encodeURIComponent(filename)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  loadProgram: (filename) => postJson('/file/load_program', { filename }),

  // Configs
  fetchConfigs: async () => {
    const res = await fetch(`${API_BASE}/config`);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  readConfig: async (filename) => {
    const res = await fetch(`${API_BASE}/config/${encodeURIComponent(filename)}`);
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
    const res = await fetch(`${API_BASE}/system/version`)
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  }
};