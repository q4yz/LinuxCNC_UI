# LinuxCNC Web UI — Project Architecture & Development Rulebook

**Last Updated:** May 16, 2026  
**Audience:** AI Agents, developers, and maintainers working on this monorepo.

This document is the **single source of truth** for architectural decisions, constraints, and patterns used in this project. All future development MUST strictly adhere to these rules to maintain consistency, safety, and scalability.

---

## 1. Project Overview & Stack

### Vision
A modern, network-accessible web dashboard for LinuxCNC machines that runs on standard PCs (with or without real CNC hardware) and is accessible from any device on the local network.

### Technology Stack

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| **Frontend** | Vue 3 | ^3.5.x | Reactive UI framework |
| | Vite | ^8.0.x | Lightning-fast dev server & bundler |
| | TailwindCSS | ^4.x | Utility-first styling |
| | Axios | ^1.x | HTTP client for API calls |
| | Pinia | ^3.x | State management (Pinia stores) |
| **Backend** | FastAPI | Latest | High-performance REST & WebSocket API |
| | Python | 3.8+ | Core language |
| | Pydantic | ^2.x | Data validation & serialization |
| | Uvicorn | Latest | ASGI server |
| | configparser | Built-in | INI file parsing for machine config |
| **Hardware** | linuxcnc (Python API) | Optional | Real hardware interface (fallback to mock) |

---

## 2. Core Architectural Rules (Strictly Enforced)

### 2.1 Single Source of Truth (SSOT)

**Rule:** `machine_config/machine.cfg` (Klipper INI-style format) is the **absolute and only source of truth** for machine state, limits, and capabilities.

**Implications:**
- All machine metadata (axes, speed ranges, temperature sensors, heaters, etc.) must be parsed from this file.
- Frontend and backend must **dynamically adapt** to the configuration at runtime—never hardcode limits, axis counts, or feature flags in the UI.
- The `core/config_manager.py` module MUST read and validate this file on startup.
- If a feature is not declared in `machine.cfg`, the UI must gracefully hide it, not assume defaults.

**Example:**
```ini
[AXIS_0]
name = X
min_position = -100
max_position = 100
default_velocity = 500

[AXIS_1]
name = Y
...
```

The frontend reads these values and builds the UI dynamically. Changing the config rebuilds the machine state.

---

### 2.2 Separation of Concerns

**Rule:** Code is organized into three tightly bounded layers: **core**, **hardware**, and **routers/components**.

#### Core Layer (`backend/core/`)
- **Hardware-agnostic** data structures and business logic.
- No imports of `linuxcnc`, `hal`, or any hardware-specific modules.
- Responsibility:
  - Parse and validate `machine.cfg` via `configparser` and `Pydantic`.
  - Define data models (`models.py`).
  - Expose a clean API to the hardware layer.

#### Hardware Layer (`backend/hardware/`)
- **Hardware-specific** implementations.
- Imports real `linuxcnc` or falls back to `linuxcnc_mock` for testing.
- Responsibility:
  - Translate core data into HAL pin commands.
  - Manage machine state and execute commands.
  - Provide a singleton `connection` object for dependency injection.

#### Router/Component Layer (`backend/routers/`, `frontend/src/`)
- Business logic and UI rendering.
- Imports from `core/` and `hardware/` to orchestrate workflows.
- Responsibility:
  - Define REST endpoints and WebSocket streams.
  - Handle user interactions and state transitions.
  - Coordinate between frontend and hardware.

**Anti-Pattern:**
```python
# ❌ WRONG: Hardware logic in the core
from linuxcnc import stat
class MachineConfig(BaseModel):
    def jog(self, axis):
        linuxcnc.command().jog(axis)  # NO!
```

**Correct Pattern:**
```python
# ✅ RIGHT: Core defines data, hardware executes
from core.config_manager import MachineConfig
from hardware.connection import connection

def jog_axis(cmd: JogCommand):
    cfg = MachineConfig()
    connection.jog(cmd.axis, cmd.velocity)
```

---

### 2.3 Singleton State

**Rule:** All hardware interactions flow through a **single, globally accessible instance** exported from `hardware/connection.py`.

**Implementation:**
```python
# backend/hardware/connection.py
class Connection:
    def set_machine_config(self, cfg):
        self.config = cfg
    def jog(self, axis, velocity):
        # Real or mocked hardware call
        ...

connection = Connection()  # Singleton
```

**Implications:**
- Inject this singleton into the FastAPI lifespan context at startup.
- No creation of multiple hardware instances.
- Thread-safe access via locks where needed (e.g., in the jog watchdog).
- Easier to mock for testing.

---

## 3. Network & API Paradigms

### 3.1 Local Network First

**Rule:** The frontend MUST dynamically resolve API and WebSocket endpoints using `window.location.hostname`. **Never hardcode localhost, 127.0.0.1, or any static IP.**

**Implementation:**
```javascript
// ✅ CORRECT
const API_BASE = `http://${window.location.hostname}:8000/api/v1`
const WS_URL = `ws://${window.location.hostname}:8000/ws/telemetry`

// ❌ WRONG
const API_BASE = 'http://localhost:8000/api/v1'
const WS_URL = 'ws://127.0.0.1:8000/ws/telemetry'
```

**Why:** Allows seamless access from phones, tablets, and other machines on the LAN without configuration changes.

**Vite Dev Server:** Bind to `0.0.0.0` in `vite.config.js`:
```javascript
export default defineConfig({
  server: {
    host: '0.0.0.0',  // Listen on all interfaces
    proxy: {
      '/api': { target: 'http://localhost:8000' },
      '/ws': { target: 'ws://localhost:8000', ws: true }
    }
  }
})
```

### 3.2 Batched Requests

**Rule:** HTTP requests that control multiple entities (e.g., jogging multiple axes) MUST batch the data into a single request. **Never spam sequential single-axis requests.**

**Why:** Prevents command-flooding, latency accumulation, and stuttering when multiple axes move simultaneously.

**Example: Jog Endpoint**
```python
# ✅ CORRECT: Multi-axis in one request
@router.post("/jog")
def jog_axis(cmd: JogCommand):
    # cmd.velocities = { 0: 100, 1: -100 }  (X and Y at different speeds)
    for axis, velocity in cmd.velocities.items():
        execute_sync_cmd("jog", 0, JOG_CONTINUOUS, True, axis, velocity)
    return {"status": "ok"}

# ❌ WRONG: Multiple sequential requests
POST /jog { "axis": 0, "velocity": 100 }
POST /jog { "axis": 1, "velocity": -100 }
```

**Frontend Keep-Alive:**
```javascript
// ✅ CORRECT: Batch all active axes
const axesToPing = Object.keys(activeAxes).map(Number)
await http.post('/jog/keepalive', { axes: axesToPing })

// ❌ WRONG: Loop and spam
for (let axis of activeAxes) {
    await http.post('/jog/keepalive', { axis })  // Multiple requests!
}
```

---

## 4. UI & Safety Constraints

### 4.1 Safety Watchdogs: Frontend Heartbeat + Backend Timeout

**Rule:** Continuous motion (jogging, spindle, etc.) relies on a **bidirectional heartbeat**:
1. **Frontend:** Sends a keep-alive ping every **250 ms** while motion is active.
2. **Backend:** If no ping received for **500 ms**, immediately execute a STOP command.

**Why:** Network failures, browser crashes, or user navigation away must halt the machine instantly. No "coast to a stop"—full stop.

**Frontend Implementation:**
```javascript
const startJog = async (axis, direction) => {
  activeAxes.value[axis] = direction * jogSpeed.value
  await http.post('/jog', { velocities: activeAxes.value, distance: 0 })
  
  // Start heartbeat (if not already running)
  if (!heartbeatInterval) {
    heartbeatInterval = setInterval(async () => {
      const axes = Object.keys(activeAxes.value).map(Number)
      if (!axes.length) {
        clearInterval(heartbeatInterval)
        heartbeatInterval = null
        return
      }
      await http.post('/jog/keepalive', { axes })
    }, 250)
  }
}

const stopJog = async (axis) => {
  delete activeAxes.value[axis]
  await http.post('/jog/stop', { axes: [axis] })
  
  if (!Object.keys(activeAxes.value).length) {
    clearInterval(heartbeatInterval)
    heartbeatInterval = null
  }
}
```

**Backend Implementation:**
```python
active_jogs = {}
active_jogs_lock = threading.Lock()

async def jog_watchdog():
    while True:
        await asyncio.sleep(0.1)
        now = time.time()
        with active_jogs_lock:
            expired = [axis for axis, t in active_jogs.items() if now - t > 0.5]
        for axis in expired:
            logger.warning(f"WATCHDOG: No heartbeat for axis {axis}. Stopping!")
            execute_sync_cmd("jog", 0, JOG_STOP, True, axis)
```

---

### 4.2 Mobile-Safe UI

**Rule:** All interactive control components (buttons, sliders) must:
1. Use both `@mousedown` and `@touchstart` to start actions.
2. Use `@mouseup`, `@mouseleave`, `@touchend`, and `@touchcancel` to stop actions.
3. Apply `touch-none select-none` CSS classes to prevent text selection and zoom.

**Why:**
- Mobile browsers default to text selection and pinch-zoom on long press or drag.
- These interfere with control and create poor UX.
- The attributes ensure consistent behavior across desktop and mobile.

**Example: Jog Button**
```vue
<button
  class="... touch-none select-none"
  @mousedown.prevent="startJog(0, 1)"
  @touchstart.prevent="startJog(0, 1)"
  @mouseup="stopJog(0)"
  @mouseleave="stopJog(0)"
  @touchend="stopJog(0)"
  @touchcancel="stopJog(0)"
>X+ (→)</button>
```

---

### 4.3 Smart Scales: Logarithmic for Wide Ranges

**Rule:** For inputs with wide ranges (e.g., jog speed from 0.1 to 4000), use logarithmic scaling via **computed exponents**, not linear.

**Why:**
- Linear slider (0–4000) gives coarse control at low speeds (0.1–10 hard to select).
- Log scale (10^–1 to 10^3.6) gives fine resolution at low end, compressed at high end.
- Machine operators can smoothly adjust from edge-finding (0.1 mm/s) to rapid traverse (4000 mm/s).

**Implementation:**
```javascript
const sliderPos = ref(2)  // Exponent
const jogSpeed = computed(() => Math.pow(10, sliderPos.value))

// Range: -1 to 3.602
// 10^-1 = 0.1, 10^0 = 1, 10^1 = 10, 10^2 = 100, 10^3.602 ≈ 4000
```

**Template:**
```vue
<input
  v-model.number="sliderPos"
  type="range"
  min="-1"
  max="3.602"
  step="0.001"
  class="w-full h-2 bg-gray-600 rounded-lg cursor-pointer"
/>
<label>
  Jog Speed: {{ jogSpeed < 10 ? jogSpeed.toFixed(2) : jogSpeed.toFixed(1) }} mm/s
</label>
```

---

## 5. Directory Structure

```
LinuxCNC_UI/
├── backend/
│   ├── main.py                 # FastAPI app entry, lifespan manager
│   ├── requirements.txt
│   ├── core/
│   │   ├── config_manager.py   # MachineConfig (SSOT parser)
│   │   └── models.py           # Pydantic schemas
│   ├── hardware/
│   │   ├── connection.py       # Singleton Connection class
│   │   ├── linuxcnc_mock.py    # Mock linuxcnc for dev/test
│   │   └── __init__.py
│   ├── routers/                # Feature-specific endpoints
│   │   ├── jog.py             # Multi-axis jogging (batched)
│   │   ├── machine.py
│   │   ├── websocket.py       # Telemetry broadcast
│   │   ├── files.py
│   │   ├── config.py
│   │   └── ...
│   └── services/
│       └── klipper_parser.py   # INI file utilities
├── frontend/
│   ├── package.json
│   ├── vite.config.js          # Host 0.0.0.0, proxy to localhost:8000
│   ├── tailwind.config.js
│   ├── index.html
│   ├── src/
│   │   ├── main.js
│   │   ├── App.vue             # Layout wrapper only
│   │   ├── style.css
│   │   ├── components/         # One component per feature
│   │   │   ├── JogControls.vue       # Logarithmic speed slider, batched jog
│   │   │   ├── TemperaturePanel.vue
│   │   │   ├── ConsolePanel.vue
│   │   │   ├── DroPanel.vue
│   │   │   └── ...
│   │   ├── stores/             # Pinia stores
│   │   │   ├── machine.js      # Machine state, WebSocket connection
│   │   │   └── console.js
│   │   ├── services/
│   │   │   └── api.js          # Axios instance, API helpers
│   │   ├── config/
│   │   │   └── gcodes.js       # G-code generation helpers
│   │   └── views/              # Page-level components
│   └── public/
├── machine_config/
│   └── machine.cfg             # ⭐ SINGLE SOURCE OF TRUTH
├── gcodes/                      # Sample NC programs
├── scripts/
│   └── update.sh
├── AI_INSTRUCTIONS.md          # Original AI constraints
├── PROJECT_ARCHITECTURE.md     # This file
└── README.md
```

---

## 6. API Endpoints & Contracts

### Multi-Axis Jog (Batched)

**POST /api/v1/machine/jog**
```json
{
  "velocities": { "0": 100, "1": -50, "2": 0 },
  "distance": 0.0
}
```
Response: `{ "status": "ok", "results": {...} }`

**POST /api/v1/machine/jog/keepalive**
```json
{
  "axes": [0, 1]
}
```
Response: `{ "status": "ok" }`

**POST /api/v1/machine/jog/stop**
```json
{
  "axes": [0, 1]
}
```
Response: `{ "status": "ok" }`

### Machine State (WebSocket)

**WS /api/v1/ws/telemetry**

Broadcast every 100 ms:
```json
{
  "type": "status",
  "data": {
    "task_state": 4,
    "estop": 0,
    "position": [10.5, 20.3, 5.1, ...],
    "temperatures": { "bed": 60.0, "nozzle": 210.5 },
    ...
  }
}
```

---

## 7. Common Patterns

### Creating a New Route

1. Define Pydantic models in the route file or `core/models.py`.
2. Use `APIRouter` with `prefix`, `tags`, and doc strings.
3. Inject hardware via the `connection` singleton (no dependency injection, keep it simple).
4. Return consistent JSON (e.g., `{ "status": "ok" }` or error details).

```python
from fastapi import APIRouter
from pydantic import BaseModel
from hardware.connection import connection

router = APIRouter(prefix="/api/v1/machine", tags=["Example"])

class ExampleCommand(BaseModel):
    value: float

@router.post("/example", summary="Do something", description="...")
def example_route(cmd: ExampleCommand):
    result = connection.execute_something(cmd.value)
    return { "status": "ok", "result": result }
```

### Creating a New Component

1. Place it in `src/components/` with a descriptive name.
2. Use `<script setup>` Composition API.
3. Import only the Pinia stores it needs (`useMachineStore`, `useConsoleStore`, etc.).
4. Import helper functions (API, utilities).
5. Use `storeToRefs()` for reactive template bindings.
6. Apply TailwindCSS for styling.

```vue
<script setup>
import { computed } from 'vue'
import { useMachineStore } from '../stores/machine'
import { storeToRefs } from 'pinia'

const store = useMachineStore()
const { status, temperatures } = storeToRefs(store)

const isMachineOn = computed(() => status.value.task_state === 4)
</script>

<template>
  <div class="bg-gray-800 rounded-lg p-4">
    <p v-if="isMachineOn" class="text-green-400">Machine: ON</p>
    <p v-else class="text-red-400">Machine: OFF</p>
  </div>
</template>
```

### Using Axios in a Component or Store

```javascript
import { api } from '../services/api'

const result = await api.setMachineState('on')
const files = await api.fetchFiles()
```

If you need a custom request, use the Axios instance directly:
```javascript
import axios from 'axios'

const http = axios.create({
  baseURL: `http://${window.location.hostname}:8000/api/v1`
})

await http.post('/custom', { data: 'value' })
```

---

## 8. Anti-Patterns & What NOT to Do

| ❌ Anti-Pattern | ✅ Correct | Reason |
|---|---|---|
| Hardcode `localhost:8000` in JS | Use `window.location.hostname` | LAN accessibility |
| Spam single-axis `/jog` requests | Batch axes in one request | Prevent stuttering & flooding |
| Store machine limits in Vue `ref` | Parse from `machine.cfg` at startup | SSOT compliance |
| Import linuxcnc in `core/` | Keep `core/` hardware-agnostic | Clean separation of concerns |
| Create multiple `Connection` instances | Inject the singleton | Thread safety & consistency |
| Prop-drill state through 5 components | Use Pinia stores | Maintainability |
| Hardcode G-code in components | Use `src/config/gcodes.js` helpers | Reusability & testability |
| Skip keep-alive during continuous motion | Implement 250 ms heartbeat + 500 ms watchdog | Safety |
| Linear slider for 0–4000 range | Use logarithmic (10^x) scale | Precision & usability |
| Text selection on jog buttons | Add `touch-none select-none` | Mobile UX |

---

## 9. Development Workflow

### Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt

cd ../frontend
npm install
```

### Development Servers
```bash
# Backend (from backend/)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Frontend (from frontend/)
npm run dev
```

Access at: `http://<your-machine-ip>:5173`

### Build for Production
```bash
# Frontend
npm run build

# Backend uses uvicorn or similar in production
```

---

## 10. Key Files & Their Responsibilities

| File | Owner | Purpose |
|------|-------|---------|
| `machine_config/machine.cfg` | DevOps/User | SSOT for machine metadata |
| `backend/core/config_manager.py` | Backend Eng | Parse & validate config |
| `backend/hardware/connection.py` | Backend Eng | Singleton hardware interface |
| `backend/main.py` | Backend Eng | FastAPI app, lifespan, WebSocket broadcast |
| `frontend/src/stores/machine.js` | Frontend Eng | Machine state & WebSocket client |
| `frontend/src/services/api.js` | Frontend Eng | Axios helpers & API contracts |
| `frontend/src/components/*.vue` | Frontend Eng | UI features (one component per feature) |
| `AI_INSTRUCTIONS.md` | All | General AI constraints & rules |
| `PROJECT_ARCHITECTURE.md` | All | This comprehensive rulebook |

---

## 11. Checklist for New Features

Before committing new code, verify:

- [ ] **Config:** Does my feature reference `machine.cfg` for any limits, names, or ranges?
- [ ] **SSOT:** Is the config read at startup and cached in `MachineConfig`?
- [ ] **Hardware Abstraction:** Are hardware calls isolated in `hardware/` or via the `connection` singleton?
- [ ] **Batching:** Do multi-entity requests batch data in a single HTTP call?
- [ ] **Safety:** Does continuous motion include a 250 ms frontend heartbeat & backend watchdog?
- [ ] **Network:** Are endpoints resolved via `window.location.hostname`, never hardcoded IPs?
- [ ] **Mobile:** Do interactive buttons include `@touchstart`, `@touchend`, `touch-none select-none`?
- [ ] **Logging:** Does the code log key events (startup, errors, watchdog triggers)?
- [ ] **Documentation:** Is the feature documented in comments or this file?
- [ ] **Testing:** Have you tested on both desktop (mouse) and mobile (touch)?

---

## 12. Troubleshooting & Common Issues

### "Command not found" or "module not found"
**Check:** Verify virtual environment is activated (`source venv/bin/activate`).

### "Cannot connect to localhost:8000" from phone
**Check:** Frontend running with `host: '0.0.0.0'` in `vite.config.js`? Backend listening on `0.0.0.0:8000`?

### Jogging stutters or feels delayed
**Check:** Are you batching jog requests? Single-axis requests cause queuing. Use the multi-axis `/jog` endpoint.

### Machine does not stop on network disconnect
**Check:** Is the backend watchdog running in `main.py`? Does it log warnings?

### Slider feels too coarse at low speeds
**Check:** Are you using a log scale? See section 4.3.

### UI text highlights on mobile jog buttons
**Check:** Add `touch-none select-none` to button classes.

---

## 13. Future Enhancements

Candidates for future work (maintain this architecture):

- [ ] Multi-machine support (one dashboard, many CNC machines on the network).
- [ ] Persistent configuration UI (edit `machine.cfg` from the web UI).
- [ ] Real-time telemetry graphing (temperatures, tool wear, cycle time).
- [ ] Automated probe routines (edge finding, calibration workflows).
- [ ] Mobile app (React Native wrapping the same API).
- [ ] Time-series database (InfluxDB) for long-term data logging.

---

## Final Note

This document is **living and evolving**. If you discover new patterns, anti-patterns, or constraints, update this file and commit the changes with a clear explanation.

**All future AI agents must read and strictly follow this architecture.**

---

**Project Lead:** [Your Name/Team]  
**Last Reviewed:** May 16, 2026  
**Next Review:** [Schedule as needed]
