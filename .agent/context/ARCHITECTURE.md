# Architecture

## Overview

A monorepo with two services:

- **`backend/`** — Python 3 FastAPI + Uvicorn. REST endpoints, a
  high-frequency WebSocket telemetry stream, and a pluggable module
  registry.
- **`frontend/`** — Vue 3 + Vite + Pinia SPA. Reactive UI, a
  Three.js 3D toolpath viewer, and a single-file lazy module
  registry that mirrors the backend.

The two services run in separate processes and communicate over
HTTP + WebSocket. The Vite dev server proxies `/api` and `/ws` to
the backend on port 8000 so the SPA sees a single origin.

The **GraphLLM orchestrator** sits above both: it is the AI agent
runtime that drives code changes, runs the verification pipeline
defined in `.agent/TEST.md`, and produces the audits / PRs. The
orchestrator is not part of the application code — it lives in
`scripts/` and reads the `.agent/` contracts. Inside the
application, the closest thing to a "node graph" is the **module
registry graph** (see `§ 4`) and the **event bus** (see `§ 5`).

## 1. Backend layout

```
backend/
├── main.py                     # FastAPI app + lifespan + router includes
├── core/                       # Hardware-agnostic: models, config parser, registry
│   ├── config_manager.py       # Parses machine_config/machine.cfg
│   ├── event_bus.py            # Frozen-payload pub/sub
│   ├── module_registry.py      # Discovers modules; mounts routers + settings
│   ├── protocols.py            # PluggableModule / ModuleManifest / ModuleContext
│   ├── settings_store.py       # atomic-write settings persistence
│   └── telemetry/              # WebSocket telemetry transport
├── hardware/                   # Hardware abstraction layer
│   ├── connection.py           # Singleton connection; falls back to mock
│   └── linuxcnc_mock.py        # In-memory simulation for dev
├── modules/                    # Pluggable feature modules
│   ├── camera/                 # Module package: module.py, router.py, settings.py
│   ├── machine/                # DRO + jog + watchdog (safety-critical)
│   ├── machineconfig/          # Profiles editor + compilers + deploy
│   ├── program/                # Lifecycle: run / pause / resume / stop
│   ├── temperature/            # Sensor polling + charting
│   └── tools/                  # Spindle + extruder MDI
├── routers/                    # Legacy flat routers (websocket, files, system)
├── services/                   # Cross-module service objects (hal_compiler, etc.)
└── tests/                      # pytest: 240+ tests for module contracts + watchdogs
```

### 1.1 Hardware Abstraction Layer

`backend/hardware/connection.py` exposes a singleton `connection`
object. On a real LinuxCNC box it imports the official `linuxcnc`
Python API; on a developer machine it falls back to
`backend/hardware/linuxcnc_mock.py` automatically. Feature code
never imports `linuxcnc` directly — it calls `execute_sync_cmd(...)`
on the connection, so the backend stays portable.

### 1.2 Safety watchdogs

The machine module's `jog_watchdog.py` runs as a background
asyncio task. The watchdog wakes every 100 ms and force-stops any
axis whose last keep-alive ping is older than
`jog_watchdog_timeout_ms` (default **500 ms**). The frontend
schedules its keep-alive at `keepalive_interval_ms` (default
**250 ms**). The 2:1 cadence is the documented contract; breaking
the cadence is a safety regression.

## 2. Frontend layout

```
frontend/src/
├── core/                       # Cross-module: registry, event-bus, settings, telemetry
├── modules/                    # Self-contained feature modules
│   ├── camera/                 # CameraPanel, manifest, store
│   ├── machine/                # DroPanel, JogControls, store, WebSocket transport
│   ├── machineconfig/          # ProfilesExplorer, CompilerPanel, DeploymentPanel, …
│   ├── temperature/            # TemperaturePanel, TemperatureSettingsPanel
│   └── tools/                  # ToolPanel (spindle + extruder)
├── components/                 # Legacy / shared widgets (AppSidebar, ConsolePanel)
├── views/                      # Route components (DashboardView, EditorView, FilesView, SettingsView)
├── stores/                     # Legacy top-level Pinia stores (console, machine, machineStore, editor)
├── router/                     # Vue Router config (hash history)
├── config/                     # Centralized G-code constants + helpers (no hardcoding in components)
├── services/                   # Generated OpenAPI client + helpers
├── generated/api/              # OpenAPI-generated service classes (gitignored)
└── *.vue, *.js                 # App shell, main.js, style.css
```

### 2.1 Composition API discipline

Every component uses `<script setup>` + the Composition API. State
that crosses component boundaries lives in Pinia stores; components
destructure with `storeToRefs()` so reactivity is preserved. Cross-
store dependencies are resolved inside actions, not at module scope,
to avoid Pinia initialization-order crashes.

### 2.2 Router

Vue Router in **hash mode** (`createWebHashHistory`) keeps the
build compatible with static hosting. The static route table in
`frontend/src/router/index.js` carries only the four built-ins
(`dashboard`, `programs` + `programs-file`, `config`, `settings`).
Module-owned routes are added at boot by
`router/index.js::registerModuleRoutes(registry)`, which walks the
mounted modules after `registry.boot()` resolves and registers
one `/<sidebar.id>` route per entry with a sidebar. The
`MainApp.vue` shell then mounts the module's exported `mainView`
component via the registry's `record.mainView` slot — the
placeholder route component never actually renders.

The contract:

* Sidebar **id** doubles as the route **name** (no separate
  translation table; `AppSidebar.vue::navigate(id)` is
  `router.push({ name: id })`).
* Built-in route names win over a colliding module-supplied name
  (the `builtInNames` set inside `registerModuleRoutes`).
* Excluded modules (via `MODULES_ENABLED`) get no route at all —
  the registry walks `import.meta.glob` lazily, so a whitelisted
  subset of modules is the only one that contributes routes.

The dashboard / programs / settings built-ins always render via
`<router-view>`. Module routes render via App.vue's
`moduleView` computed, which resolves the registry record's
`mainView` (preferred) or falls back to the alphabetical
`components/*.vue` glob discovery for unconverted modules.

### 2.3 State Facade

`frontend/src/stores/machineStore.js` is the **State Facade**: the
raw integers from the WebSocket (`task_state`, `interp_state`,
`estop`, `…`) plus a clean `systemState` string getter that widgets
consume. The machine module's WebSocket handler calls
`useMachineStore().updateStatus({...})` on every `full_state` /
`delta` payload, so the facade is always the latest snapshot. When
the machine module is not mounted, the facade defaults to `ESTOP`
so the UI never claims the machine is idle when we have no data.

### 2.4 Servo thread / base thread split

The dashboard reads two distinct transports from the backend,
mirroring the LinuxCNC runtime split:

* **Servo thread** — `GET /ws/telemetry`, 10 Hz WebSocket. Owns
  the time-critical fields (`task_state`, `estop`, `position`,
  `interp_state`, `g5x_index`, `errors`). Wired by the machine
  module's WebSocket handler and mirrored into the State Facade
  (see § 2.3).
* **Base thread** — `GET /api/v1/base-thread/snapshot`, 1 Hz REST.
  Bundles every slow stream the dashboard polls anyway
  (`progress`, `sensors`, `tools`). Owned by the
  `frontend/src/stores/baseThread.js` Pinia store.

The split exists because the 10 Hz WebSocket must not carry
bookkeeping fields (a 100 ms stat poll would re-read the full
sensor / tool list and clog NML), and the 1 Hz snapshot must not
become the time-critical transport (the DRO / Estop panels would
jitter).

The `baseThread` store is a Pinia OPTIONS-API store with three
top-level refs (`progress`, `sensors`, `tools`). Consumer modules
read via `storeToRefs(baseThread)` and watch with `deep: true` so
the top-level reassignment propagates across module boundaries.
The store is booted once in `App.vue` at the top level of
`<script setup>` (`useBaseThreadStore().start()`). The full
contract — including how to add a new stream — is in
`frontend/src/stores/baseThread.js` § USAGE and in
`.agent/STATE.md` § 12.

## 3. Config invariants

| Source | Consumers |
|--------|-----------|
| `machine_config/machine.cfg` | Frontend parses for axis counts, limits, capabilities. Backend `core/config_manager.py` parses for the same. |
| `frontend/src/config/gcodes.js` | Every `.vue` component / Pinia action that emits G-code. Helpers like `generateSetOffset(axis, value)` keep MDI strings out of components. |
| `backend/modules/<id>/settings.py` | Pydantic defaults for module settings. The registry's `SettingsStore` falls back to these on read. |

## 4. Module registry graph

The "node graph" inside this application is the module registry
on each side. Each module is a node; the registry is the edge
manager that calls `onLoad` / `onUnload` in the right order and
mounts the module's router / settingsPanel.

```
┌─────────────────────────────────────────────────────────────┐
│                       FrontendRegistry                      │
│  boot() → import.meta glob → whitelist filter → _mount()    │
│   │                                                          │
│   ├── camera         (viewer + settings)                    │
│   ├── temperature    (polling + chart)                       │
│   ├── machine        (DRO + jog + WebSocket)                 │
│   ├── machineconfig  (profiles editor + deploy)              │
│   ├── program        (lifecycle)                             │
│   └── tools          (spindle / extruder)                    │
└─────────────────────────────────────────────────────────────┘
```

The backend has a structurally identical registry
(`backend/core/module_registry.py`) that mirrors the frontend
graph. The two registries discover the same module ids on either
side; the manifest id is the contract.

**Lazy boot.** Both registries use `import.meta.glob` (frontend) and
`importlib.import_module` (backend) with lazy semantics. A module
whose view is never mounted (or whose router is never hit) never
pays an initialization cost.

**Nullable-module guarantee.** Deleting a module folder leaves the
rest of the app booting and building. The dashboard's machine slot
renders a placeholder card when the registry reports the module
absent; the build succeeds because the Vite glob is lazy.

## 5. Event bus

`backend/core/event_bus.py` and `frontend/src/core/modules/event-bus.js`
share the same contract:

- **Frozen payload.** Every `publish` re-instantiates a deep-cloned,
  deep-frozen copy of the payload before fanning out. A buggy
  subscriber mutating its copy throws in strict mode and the bus
  catches + logs the throw, then continues to the next subscriber.
- **Telemetry bus is the opposite.** The high-frequency stream
  delivers by reference so we don't pay a clone cost per tick.
  Subscribers must clone before storing.

## 6. Cross-cutting layers

| Concern | Where it lives |
|---------|----------------|
| Generated OpenAPI client | `frontend/generated/api/` (gitignored, regenerated by `scripts/generate-api.mjs`) |
| Module contracts | `.agent/contracts/{backend,frontend,settings}-module.md` |
| Settings persistence | `backend/core/settings_store.py` (atomic write per module) |
| Test scripts | `frontend/tests/*.mjs`, `backend/tests/test_*.py` |
| Repository agent guide | `.agent/AGENT.md` |
| Test run script | `.agent/TEST.md` (the orchestrator runs this) |
| Module design backlog | `MODULE_SYSTEM_ROADMAP.md` at the repo root |
| Current as-built state | `.agent/STATE.md` |

## 7. `hardware.json` v2 — the canonical machine record

`hardware.json` is the compiler's output that describes every pin
the backend knows about. Pointed at by the deployment tools,
the temperature module (which seeds its sensors from
`temperature_sensors`), and the jog watchdog (which reads
`endstops`). Versioned at the root: `"version": "2.0"`. Old
shape is rejected on load (no backcompat).

The model is flat with explicit `id` fields and string
references. Cross-references are validated by a single
`HardwareJson` Pydantic model in
`backend/modules/machineconfig/models/hardware_json_models.py`
that walks the graph once and fails fast with the full error list
when any link is unresolved.

```
Top-level keys
--------------
version       Literal["2.0"]            — breaking-change fence
machine       str                        — profile name
source        str                        — compiler id
kinematics    str
hal_type      str
axes          [Axis]                     — kinematic axes
steppers      [Stepper]                  — physical stepper drives
drivers       [Driver]                   — TMC2209 / etc.
endstops      [Endstop]                  — three per switch
heaters       [Heater]
temperature_sensors  [TemperatureSensor]   — type-discriminated list
                                         (future pressure_sensors,
                                          flow_sensors are separate
                                          top-level lists)
fans          [Fan]
```

The endstop list deliberately contains **three records per
Klipper `[endstop_switch NAME]`** — one per role:

| Role | Meaning |
|------|---------|
| `endstop` | The actual endstop — what's compiled into the kinematic constraints |
| `homing` | The homing switch — used to find the home position |
| `ignore` | Same physical pin, but flagged for macros only |

All three share the same `endstop_id` (the Klipper switch name)
and the same `pin`. The cross-reference validator enforces that
every `endstop_id` has at least one `type: "endstop"` record; a
switch with only `homing` or `ignore` records has no real endstop
binding and the model rejects it.

The `heater.sensor` reference resolves into
`temperature_sensors[].id` — not into any future
`pressure_sensors` or `flow_sensors` list. The list name is the
type discriminator; cross-type references are rejected by
construction. This is the property that lets future sensor types
land without breaking the existing wiring.

The frontend does not parse the v2 shape directly. It reads
`hardware.json` via `GET /active/content/hardware.json` (raw
text) and displays it in `CompiledOutputViewer`. The v2 model
replaces the v1 "anonymous dicts in arrays" layout; the
`hardware.json` schema is enforced at compile time, not at HTTP
boundary.

## 8. What the GraphLLM orchestrator actually does

The orchestrator is not part of the application code — it lives
outside the repo and reads the `.agent/` contracts. Inside the repo,
its footprint is:

- `.agent/AGENT.md` — repository agent guide; stack layout,
  conventions, and quality/scope rules any agent reads before
  editing code.
- `.agent/TEST.md` — the bash script the orchestrator runs after
  every edit to verify the change.
- `.agent/contracts/` — Python + JS interface contracts the AI
  must respect.
- `scripts/minimax_local.py` — local MiniMax M3 proxy used by the
  orchestrator's editor scripts.

The orchestrator's responsibilities (commit, push, run the full
test matrix, open the PR) are explicitly **not** the AI agent's
job. The agent edits code; the orchestrator ships it.
