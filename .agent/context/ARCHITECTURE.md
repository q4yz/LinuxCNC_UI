# Architecture

## Overview

A monorepo with three services:

- **`backend/machine/`** — Python 3 FastAPI + Uvicorn, port 8000.
  Everything that needs a *live* LinuxCNC session: the
  high-frequency WebSocket telemetry stream, NML state/MDI/jogging,
  program execution, tools/temperature/camera HAL interactions, and
  the Visual HAL editor feed. Per-domain routers are mounted from
  `main.py:_MODULE_DOMAINS`, same flat-table pattern as before the
  split. See `.agent/contracts/backend-router.md` for the canonical
  router contract.
- **`backend/system/`** — Python 3 FastAPI + Uvicorn, port 8001. The
  **always-running** half: machine-config profile CRUD/compile/deploy,
  NGC program uploads, macro/M-code CRUD, version/update, and the
  LinuxCNC *process* lifecycle (start/stop/switch — see `§ 1.3`).
  Stays reachable even when the machine backend or LinuxCNC itself
  is down.
- **`backend/common/`** — shared library imported by both apps
  (settings store, event bus, DTOs, domain file services, hardware
  abstraction, exceptions, …). Not a running service — see `§ 1.1`.
- **`frontend/`** — Vue 3 + Vite + Pinia SPA. Reactive UI, a
  Three.js 3D toolpath viewer, and a single-file lazy module
  registry that mirrors the backend.

The frontend never talks to `backend/machine` or `backend/system`
directly — nginx (production) / the Vite dev proxy (dev) route each
`/api/v1/...` path prefix to whichever service owns it, so the SPA
sees a single origin. See `§ 1.4` for the routing table. WebSocket
traffic (`/ws/`) always goes to the machine backend.

The **GraphLLM orchestrator** sits above all of it: it is the AI agent
runtime that drives code changes, runs the verification pipeline
defined in `.agent/TEST.md`, and produces the audits / PRs. The
orchestrator is not part of the application code — it lives in
`scripts/` and reads the `.agent/` contracts. Inside the
application, the closest thing to a "node graph" is the **module
registry graph** (see `§ 4`) and the **event bus** (see `§ 5`).

## 1. Backend layout

```
backend/
├── common/                     # Shared library — imported by both apps, never run directly
│   ├── core/                   # settings_store.py, event_bus.py, field_masking.py, models.py
│   ├── dtos/                   # Frozen dataclass domain DTOs + HalPin handles
│   ├── mappers/, factories/    # DTO ↔ Pydantic Response translation
│   ├── models/                 # Pydantic request/response + per-module settings
│   ├── domain_file_services/   # File-tree services shared by both apps + paths.py
│   │                           # (single source of truth for machine_config/, nc_files/, macros/)
│   ├── hardware/                # Hardware abstraction layer (see § 1.1)
│   ├── storage/                # Filesystem-backed persistence (MacroStorage, …)
│   ├── exceptions/, module_settings_router.py
│   └── tests/                  # Tests for the shared library itself
├── machine/                    # Machine backend — port 8000 (see Overview)
│   ├── main.py                 # FastAPI app + lifespan (telemetry loop, mock seed, watchdog)
│   ├── routers/                # axis, camera, hal, program, state, temperature, tools,
│   │                           # BaseThreadRouter/ServoThreadRouter (legacy flat + WS),
│   │                           # macro_start (POST /{name}/start only — CRUD lives in system)
│   ├── services/                # Per-domain service singletons + cross-domain facades
│   ├── hal_service/, dtos/, mappers/, factories/  (machine-only)
│   └── tests/
├── system/                     # System service — port 8001 (see Overview)
│   ├── main.py                 # Minimal lifespan; always-on
│   ├── routers/                # machineconfig, FilesRouter (programs), SystemRouter,
│   │                           # macros (CRUD only), machine_lifecycle
│   ├── services/                # machineconfig/ (compiler), machinetemplates/,
│   │                           # MachineLifecycleService (start/stop/switch — § 1.3)
│   └── tests/
├── requirements.txt             # Shared dependency set (one venv for both apps)
├── requirements-machine.txt     # -r requirements.txt (machine-only deps go here later)
└── requirements-system.txt      # -r requirements.txt (system-only deps go here later)
```

Each app's own imports stay **flat** (`from services.X import Y`,
`from core.settings_store import ...`) — every entrypoint
(`main.py`, and each app's `tests/conftest.py`) pushes
`backend/common` onto `sys.path` ahead of its own directory, so a
shared module and an app-local module never need different import
syntax. A module id owned by one process is *never* imported by the
other (the routing table in `§ 1.4` doubles as the ownership map,
since each path prefix belongs to the app that owns the module
behind it) — that's what makes the split safe: no in-memory
`SettingsStore` cache can ever go stale across processes.

**Running tests.** Each app's suite must be run as a **separate**
pytest invocation — `pytest backend/common/tests`,
`pytest backend/machine/tests`, `pytest backend/system/tests` — not
combined in one command. All three directories are named `tests`
with no `__init__.py`-rooted common package, so pytest's module
cache collides (`ImportPathMismatchError`) if it tries to collect
more than one of them in the same process.

There is **no `backend/modules/` directory** in either app. The
previous `PluggableModule` plugin system was retired; routers live
directly under `<app>/routers/<id>.py` and are mounted in that
app's `main.py` via its own `_MODULE_DOMAINS` table. See
[`.agent/contracts/backend-router.md`](.agent/contracts/backend-router.md)
for the canonical contract, and
[`.agent/context/BACKEND_LAYERS.md`](.agent/context/BACKEND_LAYERS.md) for the
Router → Service → DTO → Mapper → Storage split every per-domain
module follows.

### 1.1 Hardware Abstraction Layer

`backend/common/hardware/Connection.py` exposes the hardware
abstraction (imported as `from hardware import ...` by machine-side
code). On a real LinuxCNC box it imports the official `linuxcnc`
Python API; on a developer machine it falls back to
`backend/common/hardware/mock/` automatically. Feature code never
imports `linuxcnc` directly — it calls `execute_sync_cmd(...)` on
the connection, so the backend stays portable. Only the **machine**
backend uses this at runtime (it owns the live NML/HAL session);
the system service never touches it.

### 1.2 Safety watchdogs

The machine module's `jog_watchdog.py` runs as a background
asyncio task. The watchdog wakes every 100 ms and force-stops any
axis whose last keep-alive ping is older than
`jog_watchdog_timeout_ms` (default **500 ms**). The frontend
schedules its keep-alive at `keepalive_interval_ms` (default
**250 ms**). The 2:1 cadence is the documented contract; breaking
the cadence is a safety regression.

### 1.3 Machine process lifecycle

`backend/system/services/MachineLifecycleService.py` owns the
**LinuxCNC process** (distinct from HAL "machine power" — that's
`MachineService.py` in the machine backend, an NML-level on/off
toggle on an already-running session). It's mounted at
`/api/v1/system/machine` in the system service specifically so the
machine can be started/stopped/switched even while the machine
backend or the machine itself is down:

- `GET /api/v1/system/machine` — `pgrep`-based detection of a live
  `linuxcnc`/`emc`/`milltask`/`linuxcncsvr` session, plus whether a
  generated INI exists under `machine_config/active/`.
- `POST /api/v1/system/machine/start` — runs the console command
  `linuxcnc <machine_config/active/machine.ini>` as a detached
  process (`start_new_session=True`), console output tee'd into
  `logs/linuxcnc_console.log`. The command is overridable via the
  `LINUXCNC_START_COMMAND` env var (a `{ini}`-templated string) for
  setups that need e.g. `xterm -e linuxcnc {ini}`.
- `POST /api/v1/system/machine/stop` — SIGINT → (grace period) →
  SIGTERM → SIGKILL escalation.
- `POST /api/v1/system/machine/switch` — stop → optionally compile a
  profile → deploy staged artifacts into `active/` → start.

### 1.4 Two-backend routing (nginx / Vite dev proxy)

Both `install.sh` (nginx, production) and `frontend/vite.config.mjs`
(`DEV_PROXY`, dev/preview) implement the same routing table, mapping
path prefixes to whichever service owns that domain:

| Path | Owner |
|------|-------|
| `/api/v1/modules/macros/{name}/start` (regex — wins over the prefixes below) | machine :8000 |
| `/api/v1/system/` | system :8001 |
| `/api/v1/programs/` | system :8001 |
| `/api/v1/modules/machineconfig/` | system :8001 |
| `/api/v1/modules/macros/` (CRUD) | system :8001 |
| `/api/` (everything else) | machine :8000 |
| `/ws/` | machine :8000 |

The frontend's typed API client is generated from **both** services'
merged OpenAPI schema — `frontend/scripts/generate-api.mjs` fetches
`:8000/openapi.json` and `:8001/openapi.json` and
`frontend/scripts/merge-openapi.mjs` combines them (failing loudly on
a genuine path collision; each app's own bare `/` health check is
the one expected, intentionally-ignored collision).

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

`frontend/src/stores/stateFacade.js` is the **State Facade**: the
raw integers from the WebSocket (`task_state`, `interp_state`,
`estop`, `…`) plus a clean `systemState` string getter that widgets
consume. The servo-thread store calls
`useStateFacadeStore().updateStatus({...})` on every `full_state` /
`delta` payload, so the facade is always the latest snapshot. When
the machine module is not mounted, the facade defaults to `ESTOP`
so the UI never claims the machine is idle when we have no data.

### 2.4 Servo thread / base thread split

The dashboard reads two distinct transports from the backend,
mirroring the LinuxCNC runtime split:

* **Servo thread** — `GET /ws/telemetry`, 10 Hz WebSocket. Owns
  the time-critical fields (`task_state`, `estop`, `position`,
  `interp_state`, `g5x_index`, `errors`). Transport + reactive
  state live in `frontend/src/stores/servoThread.js`; the State
  Facade is mirrored on every frame via `updateStatus()`.
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
| `machine_config/machine.cfg` | Frontend parses for axis counts, limits, capabilities. Backend `backend/common/HardwareConfigService.py` (via `backend/common/models/machineconfig/linuxcnc_models.py`) parses for the same. |
| `frontend/src/config/gcodes.js` | Every `.vue` component / Pinia action that emits G-code. Helpers like `generateSetOffset(axis, value)` keep MDI strings out of components. |
| `backend/{machine,system}/models/<id>_settings.py` | Pydantic defaults for module settings. Each app's own `main.py:_MODULE_DOMAINS` builds a `SettingsStore` from each defaults instance and falls back to it on read — a module id is owned by exactly one app (§ 4), never both. |

## 4. Module registry graph

The "node graph" inside this application is asymmetric: the
frontend has a registry, the backend has a flat mount table. The
two must stay in lockstep on module ids — the manifest id is the
contract — but the implementation shapes differ.

### Frontend — `FrontendRegistry`

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
│   ├── macros         (.macro / .ngc / mcode CRUD + execute) │
│   └── tools          (spindle / extruder)                    │
└─────────────────────────────────────────────────────────────┘
```

The registry walks `frontend/src/modules/<id>/index.ts` via a
**static, eager** glob and consumes each module's default export.
The matching TS types live in
[`frontend/src/core/modules/protocols.ts`](frontend/src/core/modules/protocols.ts).

### Backend — flat `_MODULE_DOMAINS` mount table (one per app)

There is no backend registry. **Each app** (`backend/machine/main.py`,
`backend/system/main.py`) declares its own flat tuple of the module
ids it owns and mounts each router directly — a module id belongs to
exactly one app, never both (see the ownership split in `§ 1.4`'s
routing table and the Overview):

```python
# backend/machine/main.py — module ids owned by the machine backend
_MODULE_DOMAINS = [
    ("axis", AxisSettings, axis_router.router),
    ("machine_state", StateSettings, state_router.router),
    ("program", ProgramSettings, program_router.router),
    ("temperature", TemperatureSettings, temperature_router.router),
    ("tools", ToolsSettings, tools_router.router),
    ("camera", CameraSettings, camera_router.router),
]

# backend/system/main.py — module ids owned by the system service
_MODULE_DOMAINS = [
    ("machineconfig", MachineConfigSettings, machineconfig_router.router),
    ("macros", MacrosSettings, macros_router.router),
]
```

Each `main.py` iterates its own table to mount each per-domain
router under `/api/v1/modules/<id>` and the four canonical settings
endpoints under `/api/v1/modules/<id>/settings` (settings first,
so a module's bare `/{name}` cannot shadow them).

**Eager boot.** Both surfaces use eager loading: the frontend
glob is `import.meta.glob(..., { eager: true })` and components are
imported statically inside `App.vue` and `DashboardView.vue`.
Each backend app imports its own router modules at the top of its
`main.py` (`from routers import …`) — `importlib.import_module` runs
the module's top-level code at boot. There is no "module disabled at
build time" path — every module that ships is a hard dependency.

**Modules are mandatory.** The previous nullable-module
guarantee (deleting a module folder leaves the app booting and
building) has been retired on **both** sides. On the frontend,
every entry under `frontend/src/modules/<id>/` ships its code in
the bundle and runs `onLoad` at boot. On the backend, every entry
in each app's `_MODULE_DOMAINS` is mounted via
`app.include_router(_router)`. The contract forbids `None` returns
from `FrontendModule`'s default export and from the per-domain
routers' module-level `router` binding. See `.agent/STATE.md` § 7
and § 13, plus
[`.agent/contracts/backend-router.md`](.agent/contracts/backend-router.md)
for the canonical backend contract.

## 5. Event bus

`backend/common/core/event_bus.py` and `frontend/src/core/modules/event-bus.js`
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
| Generated OpenAPI client | `frontend/generated/api/` (gitignored; regenerated from both apps' merged spec by `frontend/scripts/generate-api.mjs` + `merge-openapi.mjs`, see `§ 1.4`) |
| Backend module contract | `.agent/contracts/backend-router.md` (per-domain routers) |
| Frontend module contract | `.agent/contracts/frontend-module.md` |
| Settings contract | `.agent/contracts/settings-module.md` |
| Settings persistence | `backend/common/core/settings_store.py` (atomic write per module; one `SettingsStore` instance per module id, owned by exactly one app) |
| Backend layered pattern | `.agent/context/BACKEND_LAYERS.md` |
| Test scripts | `frontend/tests/*.mjs`, `backend/{common,machine,system}/tests/test_*.py` (run each app's suite separately — see `§ 1` note below) |
| Repository agent guide | `.agent/AGENT.md` |
| Test run script | `.agent/TEST.md` (the orchestrator runs this) |
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
[`backend/common/models/machineconfig/hardware_json_models.py`](backend/common/models/machineconfig/hardware_json_models.py)
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
